FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    iproute2 \
    iptables \
    iputils-ping \
    iperf3 \
    python3 \
    kmod \
    procps \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

CMD ["sleep", "infinity"]
