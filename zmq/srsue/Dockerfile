FROM ubuntu:22.04 AS srsue
ARG BUILD_CORES=4

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential cmake git pkg-config ca-certificates \
      libfftw3-dev libmbedtls-dev libboost-program-options-dev \
      libconfig++-dev libsctp-dev \
      iproute2 iputils-ping curl iperf3 \
      libzmq3-dev libzmq5 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /logs && chmod 777 /logs

ADD srsRAN_4G /srsRAN_4G
# Alternatively, clone the official repository:
# RUN git clone --depth 1 https://github.com/srsRAN/srsRAN_4G.git /srsRAN_4G

RUN mkdir -p /srsRAN_4G/build && \
    cd /srsRAN_4G/build && \
    cmake .. -DENABLE_EXPORT=ON -DENABLE_ZEROMQ=ON && \
    make -j${BUILD_CORES} && \
    make install && \
    ldconfig && \
    cp /srsRAN_4G/build/srsue/src/srsue /usr/bin/srsue

WORKDIR /usr/bin/