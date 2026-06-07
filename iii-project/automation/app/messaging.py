import os
from typing import Protocol
from uuid import uuid4

import boto3

from app.models import Message


class Messenger(Protocol):
    def send(self, message: Message) -> str: ...


class SimulationMessenger:
    def send(self, message: Message) -> str:
        return f"sim-{uuid4()}"


class SesMessenger:
    def __init__(self, ses=None) -> None:
        self.ses = ses or boto3.client("ses")

    def send(self, message: Message) -> str:
        source = os.environ["SES_FROM_EMAIL"]
        response = self.ses.send_email(
            Source=source,
            Destination={"ToAddresses": [message.recipient]},
            Message={
                "Subject": {"Data": message.subject},
                "Body": {"Text": {"Data": message.body}},
            },
        )
        return response["MessageId"]


class SnsMessenger:
    def __init__(self, sns=None) -> None:
        self.sns = sns or boto3.client("sns")

    def send(self, message: Message) -> str:
        if os.environ.get("ENABLE_SMS", "").casefold() != "true":
            raise RuntimeError("SMS is disabled")
        response = self.sns.publish(
            PhoneNumber=message.recipient,
            Message=message.body,
        )
        return response["MessageId"]
