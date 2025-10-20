# If there are updated dependicies, update the requirements.txt using the command: 'pip freeze > requirements.txt'
FROM python:3.10
LABEL authors="timo.sevarts"

WORKDIR /AIpersonalizer

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "personalize_page.py"]