FROM registry.access.redhat.com/ubi9/python-39 as builder
USER root
ENV POETRY_HOME=/opt/poetry \
    POETRY_VERSION=1.8.4

RUN dnf update -y --security  --nodocs --setopt install_weak_deps=False && \
    dnf clean all -y && \
    rm -rf /var/cache/yum

COPY pyproject.toml poetry.lock ./

RUN curl -sSL https://install.python-poetry.org | python - && \
    ${POETRY_HOME}/bin/poetry config virtualenvs.in-project true

RUN ${POETRY_HOME}/bin/poetry install -vv --no-root

FROM registry.access.redhat.com/ubi9/python-39
USER root

RUN dnf update -y --security  --nodocs --setopt install_weak_deps=False && \
    dnf clean all -y && \
    rm -rf /var/cache/yum && \
    fix-permissions /opt/app-root/src -P && \
    echo "" > /opt/app-root/bin/activate

COPY --chown=1123:0 pyproject.toml poetry.lock README.md ./
COPY --chown=1123:0 datasets/ llm_load_test/datasets
COPY --chown=1123:0 plugins/ llm_load_test/plugins
COPY --chown=1123:0 static/ llm_load_test/static
COPY --chown=1123:0 *.py config.yaml llm_load_test/
COPY --from=builder --chown=1001:0 /opt/app-root/src/.venv /opt/app-root/src/.venv

USER 1123
EXPOSE 8443
#CMD ["/opt/app-root/src/.venv/bin/python", "llm_load_test/api.py"]
CMD ["/opt/app-root/src/.venv/bin/python", "-m", "gunicorn", "-c", "llm_load_test/gunicorn.conf.py", "-b", "0.0.0.0:8443", "llm_load_test.api:app"]