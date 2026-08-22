FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    poppler-utils \
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir tencentcloud-sdk-python-tmt==3.0.1130 && \
    pip install --no-cache-dir -r requirements.txt

# 1. Apply numpy compatibility patch
RUN sed -i 's/np.fromstring/np.frombuffer/g' /usr/local/lib/python3.11/site-packages/pdf2zh/high_level.py || true

# 2. Patch font loader to respect custom environment variable
RUN python3 -c "import pdf2zh.high_level as hl; import inspect; path = inspect.getfile(hl); \
    content = open(path).read(); \
    content = content.replace('font_path = ', 'font_path = os.getenv(\"PDF2ZH_CUSTOM_FONT\") or '); \
    open(path, 'w').write('import os\n' + content)" || true

COPY . .

EXPOSE 8501

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8501"]
