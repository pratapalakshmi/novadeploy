FROM registry.access.redhat.com/ubi10/python-312-minimal

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root (UID 1001 is a common non-root UID on UBI images)
USER 1001

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]