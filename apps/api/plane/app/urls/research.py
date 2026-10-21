# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path
from plane.app.views.research import (
    ResearchConnectionsEndpoint,
    ResearchConnectionEndpoint,
    ResearchImportsEndpoint,
    ResearchRetryEndpoint,
    ResearchSummaryEndpoint,
    ResearchHookEndpoint,
)

prefix = "workspaces/<str:slug>/projects/<uuid:project_id>/research/"
urlpatterns = [
    path("research/hooks/<uuid:connection_id>/<str:provider>/", ResearchHookEndpoint.as_view()),
    path(prefix + "connections/", ResearchConnectionsEndpoint.as_view()),
    path(prefix + "connections/<uuid:connection_id>/", ResearchConnectionEndpoint.as_view()),
    path(prefix + "connections/<uuid:connection_id>/imports/", ResearchImportsEndpoint.as_view()),
    path(prefix + "jobs/<uuid:job_id>/retry/", ResearchRetryEndpoint.as_view()),
    path(prefix + "summary/", ResearchSummaryEndpoint.as_view()),
]
