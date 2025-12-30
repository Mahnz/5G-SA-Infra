# This Dockerfile builds srsRAN_Project with ZeroMQ (ZMQ) support.
#
# Build args
################
# OS_VERSION            Ubuntu OS version
# LIB                   uhd or dpdk (lowercase)
# LIB_VERSION           UHD or DPDK version number
# ARCH                  gcc/clang compatible arch
# BUILD_CORES             Number or empty for all
# EXTRA_CMAKE_ARGS      Extra flags for srsRAN Project

ARG OS_VERSION="24.04"

##################
# Stage 1: Build #
##################

FROM ubuntu:$OS_VERSION AS builder

RUN apt update && apt-get install -y --no-install-recommends git git-lfs ca-certificates

ADD srsRAN_Project /src
# Alternatively, clone the official repository:
# RUN git clone --depth 1 https://github.com/srsran/srsRAN_Project.git /src

# Install build dependencies (build UHD before installing extra deps like DPDK)
ARG LIB="uhd"
ARG LIB_VERSION="4.6.0.0"
ARG ARCH=native
ARG BUILD_CORES="4"

RUN /src/docker/scripts/install_dependencies.sh build && \
    /src/docker/scripts/install_${LIB}_dependencies.sh build

# Compile UHD/DPDK
RUN /src/docker/scripts/build_${LIB}.sh ${LIB_VERSION} ${ARCH} ${BUILD_CORES}

# Install extra dependencies needed by srsRAN build/runtime (e.g. ZMQ, DPDK)
RUN /src/docker/scripts/install_dependencies.sh extra

# Compile srsRAN Project and install it in the OS
ARG EXTRA_CMAKE_ARGS="-DENABLE_EXPORT=ON -DENABLE_ZEROMQ=ON -DAUTO_DETECT_ISA=False"
RUN if [ -z "$BUILD_CORES" ]; then BUILD_CORES=$(nproc); fi && \
    LIB_UPPER=$(echo $LIB | tr '[:lower:]' '[:upper:]') && \
    export ${LIB_UPPER}_DIR="/opt/${LIB}/${LIB_VERSION}" && \
    /src/docker/scripts/builder.sh -m "-j${BUILD_CORES} install" \
    #-DBUILD_TESTS=True \
    -DENABLE_${LIB_UPPER}=On \
    #-DCMAKE_CXX_FLAGS="-march=${ARCH}" \
    -DCMAKE_INSTALL_PREFIX=/opt/srs \
    ${EXTRA_CMAKE_ARGS} /src

RUN if [ -f /src/build/tests/integrationtests/ofh/ru_emulator ]; then \
    install -m 0755 /src/build/tests/integrationtests/ofh/ru_emulator /usr/local/bin/ru_emulator; \
    else \
    echo "[builder] ru_emulator not found; skipping copy"; \
    fi

################
# Stage 2: Run #
################

FROM ubuntu:$OS_VERSION

ARG LIB="uhd"
ARG LIB_VERSION="4.6.0.0"

COPY --from=builder /opt/${LIB}/${LIB_VERSION} /opt/${LIB}/${LIB_VERSION}
COPY --from=builder /opt/srs /usr/local

COPY --from=builder /src/docker/scripts/install_${LIB}_dependencies.sh /usr/local/etc/install_lib_dependencies.sh
COPY --from=builder /src/docker/scripts/install_dependencies.sh /usr/local/etc/install_srsran_dependencies.sh

ENV LD_LIBRARY_PATH=""
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/${LIB}/${LIB_VERSION}/lib/:/opt/${LIB}/${LIB_VERSION}/lib/x86_64-linux-gnu/:/opt/${LIB}/${LIB_VERSION}/lib/aarch64-linux-gnu/

ENV PATH=$PATH:/opt/${LIB}/${LIB_VERSION}/bin/

# Install srsran and lib runtime dependencies
RUN /usr/local/etc/install_srsran_dependencies.sh run && \
    /usr/local/etc/install_srsran_dependencies.sh extra && \
    /usr/local/etc/install_lib_dependencies.sh run && \
    apt-get update && apt-get install -y --no-install-recommends iproute2 iputils-ping iperf3 && \
    apt-get autoremove && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create directory logs
RUN mkdir -p /logs && chmod 777 /logs