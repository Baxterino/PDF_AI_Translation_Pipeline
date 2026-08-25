FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-ron \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-liberation2 \
    fonts-freefont-ttf \
    fonts-noto-core \
    fonts-roboto \
    fonts-texgyre \
    libgl1 \
    libglib2.0-0 \
    sed \
    curl \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Docker Compose CLI plugin
RUN mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose && \
    ln -s /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir tencentcloud-sdk-python-tmt==3.0.1130 && \
    pip install --no-cache-dir -r requirements.txt

# Apply runtime patches
RUN sed -i 's/np.fromstring/np.frombuffer/g' /usr/local/lib/python3.11/site-packages/pdf2zh/high_level.py || true
RUN python3 -c "import pdf2zh.high_level as hl; import inspect; path = inspect.getfile(hl); \
    content = open(path).read(); \
    content = content.replace('font_path = ', 'font_path = os.getenv(\"PDF2ZH_CUSTOM_FONT\") or '); \
    open(path, 'w').write('import os\n' + content)" || true

COPY . .

EXPOSE 8501

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8501"]
