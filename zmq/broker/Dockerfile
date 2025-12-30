FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnuradio python3 python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /iq && chmod 777 /iq

ADD ./iq_broker.py /app/iq_broker.py
ADD ./iq_ctl.py /app/iq_ctl.py

WORKDIR /app