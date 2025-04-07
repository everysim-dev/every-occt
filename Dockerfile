FROM emscripten/emsdk:4.0.6 AS base-image

RUN \
  apt update && \
  ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime && \
  apt install -y \
  libbz2-dev \
  ccache \
  software-properties-common && \
  rm -rf /var/lib/apt/lists/*

RUN \
  add-apt-repository ppa:deadsnakes/ppa && \
  apt install -y \
  python3.11 && \
  rm -rf /var/lib/apt/lists/* && \
  rm /usr/bin/python3 && \
  ln -s $(which python3.11) /usr/bin/python3 && \
  ln -s $(which python3.11) /usr/bin/python && \
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

RUN \
  python3 -m pip install \
  libclang==18.1.1 \
  pyyaml==6.0.2 \
  cerberus==1.3.7 \
  argparse==1.4.0 \
  plumbum==1.9.0 \
  rich==13.9.4 \
  pytest==8.3.5 \
  pytest-mock==3.14.0

ENV RAPIDJSON_VERSION=1.1.0
ENV FREETYPE_VERSION=2-13-3
ENV OCCT_VERSION=7_6_2
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

ARG threading=single-threaded
ENV threading=$threading

FROM base-image AS test-image

RUN \
  mkdir /opencascade.js/build/ && \
  mkdir /opencascade.js/dist/ && \
  /opencascade.js/src/applyPatches.py

ENTRYPOINT ["python3", "/opencascade.js/src/buildFromYaml.py"]

FROM test-image AS custom-build-image

# RUN \
#   python3 /opencascade.js/src/generateBindings.py && \
#   python3 /opencascade.js/src/compileBindings.py ${threading} && \
#   python3 /opencascade.js/src/compileSources.py ${threading} && \
#   chmod -R 777 /opencascade.js/ && \
#   chmod -R 777 /occt

ENTRYPOINT ["python3", "/opencascade.js/src/buildFromYaml.py"]
