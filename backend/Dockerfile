FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
# pycrypto (transitive from document/OCR stacks) has no py3.11 wheels; compile needs a toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "psutil>=5.9.8,<7" \
    && python -c "import psutil; print('psutil OK', psutil.__version__)" \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /usr/local/share/nltk_data \
    && python -c "import nltk; d='/usr/local/share/nltk_data'; nltk.download('punkt_tab', download_dir=d); nltk.download('punkt', download_dir=d); nltk.download('averaged_perceptron_tagger_eng', download_dir=d)" \
    && chmod -R a+rX /usr/local/share/nltk_data
ENV NLTK_DATA=/usr/local/share/nltk_data

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
