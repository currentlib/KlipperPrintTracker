FROM ghcr.io/home-assistant/base-python:3.13-alpine3.23

RUN apk add --no-cache git

WORKDIR /opt/tracker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
