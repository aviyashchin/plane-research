FROM makeplane/plane-backend:v1.4.2
USER root
RUN pip install --no-cache-dir 'Authlib==1.9.1'
COPY plane_sso /code/plane_sso
COPY tests /code/sso_tests
COPY plane_sso/settings.py /code/plane/settings/community_sso.py
COPY tests/settings.py /code/plane/settings/community_sso_tests.py
ENV DJANGO_SETTINGS_MODULE=plane.settings.community_sso
