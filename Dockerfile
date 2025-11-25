FROM python:3.10.11-slim

WORKDIR /AIpersonalizer

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

ENV FLASK_APP=app.py
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=8080"]