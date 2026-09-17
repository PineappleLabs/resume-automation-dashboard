FROM python:3.12-slim

# Pinned to the exact release the README requires (0.17+, for fontawesome5).
# Bump deliberately when needed rather than tracking "latest" -- this is the
# one binary this whole pipeline hinges on, and Watchtower must never be
# allowed to drift it out from under a running container.
ARG TECTONIC_VERSION=0.17.0
ARG TECTONIC_ASSET=tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-gnu.tar.gz

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libgraphite2-3 \
    && curl -fsSL -o /tmp/tectonic.tar.gz \
       "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/${TECTONIC_ASSET}" \
    && tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic \
    && chmod +x /usr/local/bin/tectonic \
    && rm /tmp/tectonic.tar.gz \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY resume_pipeline ./resume_pipeline
COPY content ./content
COPY templates ./templates

RUN pip install --no-cache-dir .

# jobs/ and out/ are runtime output, not part of the image -- mount a volume
# over /app/jobs (and /app/out, if used) in Compose so tailored resumes
# persist outside the container.
RUN mkdir -p jobs out

ENTRYPOINT ["python", "-m", "resume_pipeline.cli"]
CMD ["--help"]
