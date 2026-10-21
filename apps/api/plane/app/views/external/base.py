# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python import
import os
from html import escape
from typing import List, Dict, Tuple

# Third party import
from openai import OpenAI
import requests

from rest_framework import status
from rest_framework.response import Response

# Module import
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import ProjectLiteSerializer, WorkspaceLiteSerializer
from plane.db.models import Project, Workspace, Page
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import serializers
from plane.license.utils.instance_value import get_configuration_value
from plane.utils.exception_logger import log_exception

from ..base import BaseAPIView


class LLMProvider:
    """Base class for LLM provider configurations"""

    name: str = ""
    models: List[str] = []
    default_model: str = ""

    @classmethod
    def get_config(cls) -> Dict[str, str | List[str]]:
        return {
            "name": cls.name,
            "models": cls.models,
            "default_model": cls.default_model,
        }


class OpenAIProvider(LLMProvider):
    name = "OpenAI"
    models = ["gpt-3.5-turbo", "gpt-4o-mini", "gpt-4o", "o1-mini", "o1-preview"]
    default_model = "gpt-4o-mini"


class AnthropicProvider(LLMProvider):
    name = "Anthropic"
    models = [
        "claude-3-5-sonnet-20240620",
        "claude-3-haiku-20240307",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-2.1",
        "claude-2",
        "claude-instant-1.2",
        "claude-instant-1",
    ]
    default_model = "claude-3-sonnet-20240229"


class GeminiProvider(LLMProvider):
    name = "Gemini"
    models = ["gemini-pro", "gemini-1.5-pro-latest", "gemini-pro-vision"]
    default_model = "gemini-pro"


SUPPORTED_PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def get_llm_config() -> Tuple[str | None, str | None, str | None]:
    """
    Helper to get LLM configuration values, returns:
        - api_key, model, provider
    """
    api_key, provider_key, model = get_configuration_value(
        [
            {
                "key": "LLM_API_KEY",
                "default": os.environ.get("LLM_API_KEY", None),
            },
            {
                "key": "LLM_PROVIDER",
                "default": os.environ.get("LLM_PROVIDER", "openai"),
            },
            {
                "key": "LLM_MODEL",
                "default": os.environ.get("LLM_MODEL", None),
            },
        ]
    )

    provider = SUPPORTED_PROVIDERS.get(provider_key.lower())
    if not provider:
        log_exception(ValueError(f"Unsupported provider: {provider_key}"))
        return None, None, None

    if os.environ.get("LLM_BASE_URL") and not api_key:
        api_key = "local-research"

    if not api_key:
        log_exception(ValueError(f"Missing API key for provider: {provider.name}"))
        return None, None, None

    # If no model specified, use provider's default
    if not model:
        model = provider.default_model

    # Model names change independently of Plane releases. The operator selects the model.
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        return None, None, None

    return api_key, model, provider_key


def get_llm_response(task, prompt, api_key: str, model: str, provider: str) -> Tuple[str | None, str | None]:
    """Helper to get LLM completion response"""
    final_text = str(task) + "\n" + str(prompt or "")
    try:
        base_url = os.environ.get("LLM_BASE_URL")
        if not base_url and os.environ.get("LLM_ALLOW_PAID_API") != "1":
            return None, "Set LLM_BASE_URL for a local model or explicitly enable paid inference"
        if provider.lower() == "anthropic":
            response = requests.post(
                f"{(base_url or 'https://api.anthropic.com/v1').rstrip('/')}/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": final_text}]},
                timeout=90,
            )
            response.raise_for_status()
            return "\n".join(block["text"] for block in response.json()["content"] if block["type"] == "text"), None
        if provider.lower() == "gemini" and not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=90, max_retries=1)
        chat_completion = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": final_text}], max_tokens=2048
        )
        text = chat_completion.choices[0].message.content
        if not isinstance(text, str) or not text.strip():
            return None, "The model returned an empty response"
        return text, None
    except Exception as e:
        # Provider exceptions can contain credentials and user prompts.
        log_exception(RuntimeError(f"LLM request failed: {e.__class__.__name__}"))
        error_type = e.__class__.__name__
        if error_type == "AuthenticationError":
            return None, f"Invalid API key for {provider}"
        elif error_type == "RateLimitError":
            return None, f"Rate limit exceeded for {provider}"
        else:
            return None, f"Error occurred while generating response from {provider}"


class GPTIntegrationEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id):
        api_key, model, provider = get_llm_config()

        if not api_key or not model or not provider:
            return Response(
                {"error": "LLM provider API key and model are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = request.data.get("task", False)
        if not isinstance(task, str) or not task.strip() or len(task) > 2000:
            return Response({"error": "Task must contain 1 to 2000 characters"}, status=status.HTTP_400_BAD_REQUEST)

        prompt = request.data.get("prompt", "")
        if not isinstance(prompt, str) or len(prompt) > 100000:
            return Response(
                {"error": "Prompt must be text of at most 100000 characters"}, status=status.HTTP_400_BAD_REQUEST
            )
        if request.data.get("page_id"):
            page_id = serializers.UUIDField().run_validation(request.data["page_id"])
            page = get_object_or_404(
                Page.objects.filter(Q(owned_by=request.user) | Q(access=0)),
                id=page_id,
                workspace__slug=slug,
                projects__id=project_id,
                project_pages__deleted_at__isnull=True,
            )
            prompt = page.description_stripped or ""
        text, error = get_llm_response(task, prompt, api_key, model, provider)
        if not text and error:
            return Response(
                {"error": "An internal error has occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        workspace = Workspace.objects.get(slug=slug)
        project = Project.objects.get(pk=project_id, workspace__slug=slug)

        return Response(
            {
                "response": text,
                "response_html": escape(text or "").replace("\n", "<br/>"),
                "project_detail": ProjectLiteSerializer(project).data,
                "workspace_detail": WorkspaceLiteSerializer(workspace).data,
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceGPTIntegrationEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug):
        api_key, model, provider = get_llm_config()

        if not api_key or not model or not provider:
            return Response(
                {"error": "LLM provider API key and model are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = request.data.get("task", False)
        if not isinstance(task, str) or not task.strip() or len(task) > 2000:
            return Response({"error": "Task must contain 1 to 2000 characters"}, status=status.HTTP_400_BAD_REQUEST)

        prompt = request.data.get("prompt", "")
        if not isinstance(prompt, str) or len(prompt) > 100000:
            return Response(
                {"error": "Prompt must be text of at most 100000 characters"}, status=status.HTTP_400_BAD_REQUEST
            )
        text, error = get_llm_response(task, prompt, api_key, model, provider)
        if not text and error:
            return Response(
                {"error": "An internal error has occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "response": text,
                "response_html": escape(text or "").replace("\n", "<br/>"),
            },
            status=status.HTTP_200_OK,
        )


class UnsplashEndpoint(BaseAPIView):
    def get(self, request):
        (UNSPLASH_ACCESS_KEY,) = get_configuration_value(
            [
                {
                    "key": "UNSPLASH_ACCESS_KEY",
                    "default": os.environ.get("UNSPLASH_ACCESS_KEY"),
                }
            ]
        )
        # Check unsplash access key
        if not UNSPLASH_ACCESS_KEY:
            return Response([], status=status.HTTP_200_OK)

        # Query parameters
        query = request.GET.get("query", False)
        page = request.GET.get("page", 1)
        per_page = request.GET.get("per_page", 20)

        url = (
            f"https://api.unsplash.com/search/photos/?client_id={UNSPLASH_ACCESS_KEY}&query={query}&page=${page}&per_page={per_page}"
            if query
            else f"https://api.unsplash.com/photos/?client_id={UNSPLASH_ACCESS_KEY}&page={page}&per_page={per_page}"
        )

        headers = {"Content-Type": "application/json"}

        resp = requests.get(url=url, headers=headers)
        return Response(resp.json(), status=resp.status_code)
