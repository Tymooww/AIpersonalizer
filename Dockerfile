FROM python:3.10.11-slim

WORKDIR /AIpersonalizer

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python","-u","app.py"]