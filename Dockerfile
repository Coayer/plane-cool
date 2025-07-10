FROM python:alpine
COPY ./requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY . .
CMD ["python3", "main.py"]