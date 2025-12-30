# Build args
################
# OS_VERSION            Ubuntu OS version
# UHD_VERSION           UHD version number
# DPDK_VERSION          DPDK version number
# MARCH                 gcc/clang compatible arch
# NUM_JOBS              Number or empty for all
# EXTRA_CMAKE_ARGS      Extra flags for srsRAN Project

ARG OS_VERSION=24.04
ARG UHD_VERSION=4.7.0.0
ARG DPDK_VERSION=24.11.2
ARG MARCH=native

##################
# Stage 1: Build #
##################

FROM ubuntu:$OS_VERSION AS builder

ARG BUILD_CORES

# Adding the complete repo to the context, in /src folder
# ADD . /src
# Or download the full repo
RUN apt update && apt-get install -y --no-install-recommends git git-lfs ca-certificates \
    pkg-config libzmq3-dev libczmq-dev
RUN git clone https://github.com/srsran/srsRAN_Project.git /src

# Install srsRAN build dependencies
RUN /src/docker/scripts/install_dependencies.sh build && \
    /src/docker/scripts/install_uhd_dependencies.sh build && \
    /src/docker/scripts/install_dpdk_dependencies.sh build && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git clang

ARG UHD_VERSION
ARG DPDK_VERSION
ARG MARCH

# Compile UHD/DPDK
RUN /src/docker/scripts/build_uhd.sh "${UHD_VERSION}" ${MARCH} ${BUILD_CORES} && \
    /src/docker/scripts/build_dpdk.sh "${DPDK_VERSION}" ${MARCH} ${BUILD_CORES}

# Compile srsRAN Project and install it in the OS
ARG COMPILER=gcc
ARG EXTRA_CMAKE_ARGS=""
ENV UHD_DIR=/opt/uhd/${UHD_VERSION}
ENV DPDK_DIR=/opt/dpdk/${DPDK_VERSION}
RUN /src/docker/scripts/builder.sh -c ${COMPILER} -m "-j${BUILD_CORES} srscu srsdu srsdu_split_8 srsdu_split_7_2 gnb gnb_split_8 gnb_split_7_2 ru_emulator" \
    -DBUILD_TESTING=False -DENABLE_UHD=On -DENABLE_DPDK=On -DMARCH=${MARCH} -DCMAKE_INSTALL_PREFIX=/opt/srs \
    ${EXTRA_CMAKE_ARGS} /src
RUN cp /src/build/apps/cu/srscu             /tmp/srscu                     && \
    cp /src/build/apps/du/srsdu             /tmp/srsdu                     && \
    cp /src/build/apps/du_split_8/srsdu     /tmp/srsdu_split_8             && \
    cp /src/build/apps/du_split_7_2/srsdu   /tmp/srsdu_split_7_2           && \
    cp /src/build/apps/gnb/gnb              /tmp/gnb                       && \
    cp /src/build/apps/gnb_split_8/gnb      /tmp/gnb_split_8               && \
    cp /src/build/apps/gnb_split_7_2/gnb    /tmp/gnb_split_7_2             && \
    cd /src/build                                                          && \
    make install                                                           && \
    mv /tmp/srscu                           /opt/srs/bin/srscu             && \
    mv /tmp/srsdu                           /opt/srs/bin/srsdu             && \
    mv /tmp/srsdu_split_8                   /opt/srs/bin/srsdu_split_8     && \
    mv /tmp/srsdu_split_7_2                 /opt/srs/bin/srsdu_split_7_2   && \
    mv /tmp/gnb                             /opt/srs/bin/gnb               && \
    mv /tmp/gnb_split_8                     /opt/srs/bin/gnb_split_8       && \
    mv /tmp/gnb_split_7_2                   /opt/srs/bin/gnb_split_7_2

################
# Stage 2: Run #
################

FROM ubuntu:$OS_VERSION AS runtime

ARG UHD_VERSION
ARG DPDK_VERSION

# Copy srsRAN binaries and libraries installed in previous stage
COPY --from=builder /opt/uhd/${UHD_VERSION}   /opt/uhd/${UHD_VERSION}
COPY --from=builder /opt/dpdk/${DPDK_VERSION} /opt/dpdk/${DPDK_VERSION}
COPY --from=builder /opt/srs                  /usr/local

# Copy the install dependencies scripts
ADD scripts/install_uhd_dependencies.sh  /usr/local/etc/install_uhd_dependencies.sh
ADD scripts/install_dpdk_dependencies.sh /usr/local/etc/install_dpdk_dependencies.sh
ADD scripts/install_dependencies.sh      /usr/local/etc/install_srsran_dependencies.sh

ENV LD_LIBRARY_PATH=""
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/uhd/${UHD_VERSION}/lib/:/opt/uhd/${UHD_VERSION}/lib/x86_64-linux-gnu/:/opt/uhd/${UHD_VERSION}/lib/aarch64-linux-gnu/
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/dpdk/${DPDK_VERSION}/lib/:/opt/dpdk/${DPDK_VERSION}/lib/x86_64-linux-gnu/:/opt/dpdk/${DPDK_VERSION}/lib/aarch64-linux-gnu/

ENV PATH=$PATH:/opt/uhd/${UHD_VERSION}/bin/:/opt/dpdk/${DPDK_VERSION}/bin/

# Install srsran and lib runtime dependencies
RUN /usr/local/etc/install_srsran_dependencies.sh run && \
    /usr/local/etc/install_uhd_dependencies.sh run && \
    /usr/local/etc/install_dpdk_dependencies.sh run && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ntpdate iputils-ping net-tools && \
    apt-get autoremove && apt-get clean && rm -rf /var/lib/apt/lists/*

# Crea directory logs
RUN mkdir -p /logs && chmod 777 /logs
