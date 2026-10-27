from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Region = Literal['pomorskie', 'warmińsko-mazurskie', 'podlaskie']


class Model(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class Farm(Model):
    name: str = Field(min_length=2, max_length=150)
    owner: str = Field(default='', max_length=100)
    region: Region
    town: str = Field(default='', max_length=100)
    phone: str = Field(default='', max_length=40)
    herd_type: Literal['mleczne', 'mięsne', 'mieszane'] = 'mleczne'
    notes: str = Field(default='', max_length=3000)


class Animal(Model):
    farm_id: int = Field(gt=0)
    ear_tag: str = Field(min_length=4, max_length=30, pattern=r'^[A-Za-z0-9 -]+$')
    name: str = Field(default='', max_length=80)
    breed: str = Field(default='', max_length=80)
    sex: Literal['female', 'male'] = 'female'
    birth_date: date
    status: Literal['healthy', 'watch', 'treatment'] = 'healthy'
    notes: str = Field(default='', max_length=3000)

    @field_validator('birth_date')
    @classmethod
    def not_future(cls, value):
        if value > date.today():
            raise ValueError('Data urodzenia nie może być w przyszłości')
        return value

    @field_validator('ear_tag')
    @classmethod
    def tag_format(cls, value):
        return value.upper().replace(' ', '').replace('-', '')


class Visit(Model):
    farm_id: int = Field(gt=0)
    animal_id: int | None = Field(default=None, gt=0)
    scheduled_at: datetime
    reason: str = Field(min_length=3, max_length=250)
    status: Literal['planned', 'done', 'cancelled'] = 'planned'
    notes: str = Field(default='', max_length=3000)

    @field_validator('scheduled_at')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError('Wymagana strefa czasowa')
        return value


class Treatment(Model):
    animal_id: int = Field(gt=0)
    diagnosis: str = Field(min_length=3, max_length=300)
    medication: str = Field(min_length=2, max_length=150)
    dose: str = Field(min_length=1, max_length=150)
    vet: str = Field(min_length=2, max_length=120)
    treated_at: datetime
    milk_days: int = Field(ge=0, le=730)
    meat_days: int = Field(ge=0, le=730)
    notes: str = Field(default='', max_length=3000)

    @field_validator('treated_at')
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None:
            raise ValueError('Wymagana strefa czasowa')
        from datetime import timezone
        if value > datetime.now(timezone.utc):
            raise ValueError('Zabieg nie może być w przyszłości')
        return value


class Report(Model):
    title: str = Field(min_length=5, max_length=300)
    summary: str = Field(default='', max_length=2000)
    region: Region
    category: Literal['choroby zakaźne', 'wymię i mleko', 'rozród', 'żywienie', 'dobrostan', 'inne'] = 'inne'
    source_name: str = Field(min_length=2, max_length=100)
    source_url: str = Field(max_length=2000)
    source_kind: Literal['forum', 'official', 'media', 'farmer'] = 'farmer'

    @field_validator('source_url')
    @classmethod
    def https_url(cls, value):
        from urllib.parse import urlsplit
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            raise ValueError('Podaj publiczny adres HTTPS bez danych logowania')
        return value


class Review(Model):
    verification: Literal['unverified', 'reviewed', 'dismissed']
    review_note: str = Field(min_length=5, max_length=1000)


class Chat(Model):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)
