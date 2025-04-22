FROM emscripten/emsdk:4.0.7 AS base-image

RUN \
  apt update && \
  apt install -y \
  libbz2-dev \
  ccache \
  python3-apt \
  software-properties-common \
  gnupg \
  castxml && \
  rm -rf /var/lib/apt/lists/*

RUN \
  wget https://apt.llvm.org/llvm.sh && \
  chmod +x llvm.sh && \
  ./llvm.sh 20

RUN \
  apt update && \
  apt install -y \
  libclang-20-dev \
  libclang-cpp20-dev && \  
  rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV RAPIDJSON_VERSION=1.1.0
ENV FREETYPE_VERSION=2-13-3
ENV OCCT_VERSION=7_6_3
ENV _EMCC_CCACHE=1
ENV COMPILER_WRAPPER=ccache
ENV CCACHE_DIR=/opencascade.js/build/ccache
ENV EM_CACHE=/opencascade.js/build/cache
ENV CCACHE_RECACHE=1
ENV CCACHE_MAXSIZE=25G

WORKDIR /rapidjson
RUN \
  git clone --depth=1 https://github.com/Tencent/rapidjson.git .
  # 24b5e7a

WORKDIR /freetype
RUN \
  git clone --depth=1 -b VER-${FREETYPE_VERSION} https://github.com/freetype/freetype.git .

WORKDIR /occt
RUN \
  git clone --depth=1 -b V${OCCT_VERSION} https://github.com/Open-Cascade-SAS/OCCT.git .

WORKDIR /opencascade.js/
COPY src ./src
WORKDIR /src

COPY .python-version /src/.python-version
COPY pyproject.toml /src/pyproject.toml
COPY uv.lock /src/uv.lock

RUN /root/.local/bin/uv sync

ARG threading=single-threaded
ENV threading=$threading

FROM base-image AS test-image

RUN \
  mkdir /opencascade.js/build/ && \
  mkdir /opencascade.js/dist/ && \
  /root/.local/bin/uv run /opencascade.js/src/applyPatches.py

ENTRYPOINT ["/root/.local/bin/uv", "run", "/opencascade.js/src/buildFromYaml.py"]

FROM test-image AS custom-build-image

# RUN \
#   python3 /opencascade.js/src/generateBindings.py && \
#   python3 /opencascade.js/src/compileBindings.py ${threading} && \
#   python3 /opencascade.js/src/compileSources.py ${threading} && \
#   chmod -R 777 /opencascade.js/ && \
#   chmod -R 777 /occt

ENTRYPOINT ["/root/.local/bin/uv", "run", "/opencascade.js/src/buildFromYaml.py"]
