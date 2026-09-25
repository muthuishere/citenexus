# Golden-drift check: regenerate the PDF fixtures on Linux against pinned
# pdfium chromium/8066 and diff them against the committed (macOS-generated)
# files. /DRIFT in the output says "no drift" or holds the diff.
#
#   docker build --platform linux/amd64 -f rust/docker/pdf-golden.Dockerfile \
#     --output type=local,dest=<outdir> .
FROM rust:1.95-slim-bookworm AS build
ARG TARGETARCH
ARG PDFIUM_TAG=chromium/8066
ARG PDFIUM_SHA256_amd64=0b43f405477cf2cfc4dbff06905093c3309756c6bca1fb9da99234a2ca97fed2
ARG PDFIUM_SHA256_arm64=0e6f90dccbc6b81fd5d7106abaf164c4222178f024c204d00d526b60fd2ad535
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates protobuf-compiler libprotobuf-dev gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) asset=pdfium-linux-x64.tgz;   sum="$PDFIUM_SHA256_amd64" ;; \
      arm64) asset=pdfium-linux-arm64.tgz; sum="$PDFIUM_SHA256_arm64" ;; \
      *) echo "unsupported arch $TARGETARCH"; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/pdfium.tgz "https://github.com/bblanchon/pdfium-binaries/releases/download/${PDFIUM_TAG}/${asset}"; \
    echo "${sum}  /tmp/pdfium.tgz" | sha256sum -c -; \
    mkdir -p /opt/pdfium && tar xzf /tmp/pdfium.tgz -C /opt/pdfium && rm /tmp/pdfium.tgz
ENV PDFIUM_DYNAMIC_LIB_PATH=/opt/pdfium/lib/libpdfium.so
ENV CARGO_BUILD_JOBS=2
WORKDIR /src
COPY rust rust
COPY conformance conformance
COPY docs/schema docs/schema
# Regenerate the committed PDF fixtures on Linux and compare them byte for
# byte with the committed ones (they are generated on macOS). /DRIFT records
# the result; the regenerated files are exported either way for diffing.
RUN cd rust && cp -r tests/data/pdf /committed \
 && CITENEXUS_WRITE_PDF_FIXTURES=1 cargo test --profile measure --features pdf --test pdf_contract_test \
 && cp -r tests/data/pdf /out1 \
 && { cat /opt/pdfium/VERSION > /out1/PDFIUM_VERSION || true; } \
 && { if diff -r /committed tests/data/pdf > /out1/DRIFT; then echo "no drift" > /out1/DRIFT; fi; }
FROM scratch
COPY --from=build /out1 /
