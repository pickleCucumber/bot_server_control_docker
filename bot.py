import asyncio
from logic import *
import pandas as pd
import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import time
from aiogram.filters import Command, CommandObject

from aiogram.types import Chat, Message
import logging
from telegram.ext import Updater, CommandHandler
import sys
from aiogram import Bot, Dispatcher, types#, html, executor
import aioschedule
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import subprocess
import re
from sqlalchemy import create_engine, text
import gc
import os
import docker
load_dotenv()
API_token = os.getenv("API_token")
users = []
user_id = os.getenv("my_id")
users_for_send = []
users_for_calls_send=[]
names = []
save_users_for_send = []
save_users_for_calls_send=[]

#------------------------------- тут объявляем бота----------------------#
bot = Bot(token=API_token,
          default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

docker_client = docker.from_env()
# ------------------------------- Настройка логирования ------------------------------- #
def setup_logging():
    # основной логгер для приложения
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('bot.log', encoding='utf-8')
        ]
    )
    #  логгер для отслеживания изменений списков
    user_logger = logging.getLogger('user_changes')
    user_logger.setLevel(logging.INFO)
    if not user_logger.handlers:
        fh = logging.FileHandler('user_changes.log', encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        user_logger.addHandler(fh)
    return user_logger

user_logger = setup_logging()

# --------------------------------тут команды----------------------------#

#тут пока заглушка
@dp.message(Command('restart'))
async def start_command(message):
    await message.reply("Чат перезапущен")

#старт
@dp.message(Command('start'))
async def start(message: Message):
    global users, names
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    users.append(user_id)
    names.append(user_name)
    user_logger.info(f"Пользователь {user_id} ({user_name}) добавлен в список users. Текущий список: {users}")
    await message.reply("Привет! Я бот отдела рисков")

#регистрация на основную рассылку
@dp.message(Command('register'))
async def register(message: Message):
    global users_for_send, save_users_for_send
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    user_logger.info(f"Пользователь {user_id} ({user_name}) пытается зарегистрироваться на основную рассылку. "
                     f"Текущий users_for_send: {users_for_send}")

    users_for_send.append(user_id)
    # Удаляем дубликаты и сохраняем в save_users_for_send
    save_users_for_send = list(dict.fromkeys(users_for_send))

    user_logger.info(f"Регистрация успешна. Новый users_for_send: {users_for_send}, save_users_for_send: {save_users_for_send}")
    await message.reply("Теперь вы будите получать рассылку")


    return users_for_send

#отмена регистрации на основную рассылку
@dp.message(Command('cancel_register'))
async def cancel_register(message: Message):
    global users_for_send, save_users_for_send
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    user_logger.info(f"Пользователь {user_id} ({user_name}) пытается отписаться от основной рассылки. "
                     f"Текущий users_for_send: {users_for_send}")

    if user_id in users_for_send:
        users_for_send.remove(user_id)
        save_users_for_send = list(dict.fromkeys(users_for_send))
        user_logger.info(f"Отписка успешна. Новый users_for_send: {users_for_send}, save_users_for_send: {save_users_for_send}")
        await message.reply("Теперь вы не будете получать рассылку")
    else:
        user_logger.warning(f"Пользователь {user_id} ({user_name}) попытался отписаться, но его нет в users_for_send")
        await message.reply("Вы не были зарегистрированы на рассылку")

    print('users_for_send', users_for_send)
    print('save_users_for_send', save_users_for_send)

    return users_for_send

#регистрация на звонки
@dp.message(Command('register_calls'))
async def register_calls(message: Message):
    global users_for_calls_send, save_users_for_calls_send
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    user_logger.info(f"Пользователь {user_id} ({user_name}) пытается зарегистрироваться на рассылку звонков. "
                     f"Текущий users_for_calls_send: {users_for_calls_send}")

    users_for_calls_send.append(user_id)
    save_users_for_calls_send = list(dict.fromkeys(users_for_calls_send))

    user_logger.info(f"Регистрация успешна. Новый users_for_calls_send: {users_for_calls_send}, save_users_for_calls_send: {save_users_for_calls_send}")
    await message.reply("Теперь вы будите получать рассылку по звонкам")
    print('users_for_calls_send', users_for_calls_send)

    return users_for_calls_send

#отмена регистрации на основную рассылку
@dp.message(Command('cancel_call'))
async def cancel_call(message: Message):
    global users_for_calls_send, save_users_for_calls_send
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    user_logger.info(f"Пользователь {user_id} ({user_name}) пытается отписаться от рассылки звонков. "
                     f"Текущий users_for_calls_send: {users_for_calls_send}")

    if user_id in users_for_calls_send:
        users_for_calls_send.remove(user_id)
        save_users_for_calls_send = list(dict.fromkeys(users_for_calls_send))
        user_logger.info(f"Отписка успешна. Новый users_for_calls_send: {users_for_calls_send}, save_users_for_calls_send: {save_users_for_calls_send}")
        await message.reply("Теперь вы не будете получать рассылку")
    else:
        user_logger.warning(f"Пользователь {user_id} ({user_name}) попытался отписаться, но его нет в users_for_calls_send")
        await message.reply("Вы не были зарегистрированы на рассылку")

    return users_for_calls_send

#ссыло4ка на мониторинг
@dp.message(Command('info_monitoring'))
async def info_mon(message: Message):
    await message.reply("https://huggingface.co/spaces/picklecucumber/monitoring")

#ссыло4ка на разведение потоков
@dp.message(Command('info_stream_branching'))
async def info_branch(message: Message):
    await message.reply("https://www.figma.com/deck/kQ5bwvIjSYkdvg1yZ0xPkS/Customer-segmentation-models-presentation?node-id=1-1196&node-type=canvas&t=7ykCiSNbdD8CDEgD-1&scaling=min-zoom&content-scaling=fixed&page-id=0%3A1")

#последняя заявка
@dp.message(Command('last_apps'))
async def start_command(message):
    data = new_data()
    await message.answer('последняя прошедшая заявка')
    await message.answer(data.loc[0].to_string())

#последние 5 заявок
@dp.message(Command('last_five_apps'))
async def start_command(message):
    data = new_data()
    await message.answer('Последние прошедшие заявки')
    await message.answer(data.to_string())

#проблемные звонки коллекторов
@dp.message(Command('problem_calls'))
async def start_command(message):
    df = collector_calls()
    await message.answer('Звонки с нарушениями за вчера')

    if df.shape[0] == 1:
        await message.answer(df.loc[0].to_string())
    else:
        for i in range(df.shape[0]):
            await message.answer(df.loc[i].to_string())
            await message.answer('--------------------')

#pdn
@dp.message(Command('pdn'))
async def PDN(message):
    cutoff=0.03
    pdn50 = PDN_50_80()
    pdn80 = PDN_80()
    if (pdn50>cutoff)|(pdn50==cutoff):
        await message.reply((f"PDN50-80 ={pdn50} .Превышение на {round(pdn50-cutoff, 3)} за последние 3 дня"))
    else:
        await message.reply((f"PDN50-80 = {pdn50} . В норме за последние 3 дня"))
    if (pdn80>cutoff)|(pdn80==cutoff):
        await message.reply((f"PDN80+ = {pdn80} .Превышение на {round(pdn80-cutoff, 3)} за последние 3 дня"))
    else:
        await message.reply((f"PDN80+ = {pdn80} . В норме за последние 3 дня"))

@dp.message(Command('service'))
async def Service(message):
    data_OK, data_time =services()

    # df в строку
    def format_dataframe_to_string(df):
        table_string = df.to_string(index=False)
        return f"<pre>{table_string}</pre>"

    formatted_table0 = format_dataframe_to_string(data_OK.loc[data_OK['Процент ОК']<90][['ExternalServiceName','Процент ОК', 'Процент TIMEOUT']])
    formatted_table1 = format_dataframe_to_string(data_time.loc[data_time.avg_sec>data_time.avg_sec_month])

    await message.answer(formatted_table0, parse_mode=ParseMode.HTML)
    await message.answer(formatted_table1, parse_mode=ParseMode.HTML)


@dp.message(Command('all_service'))
async def all_Service(message):
    data_OK, data_time =services()

    def format_dataframe_to_string(df):
        table_string = df.to_string(index=False)
        return f"<pre>{table_string}</pre>"

    formatted_table0 = format_dataframe_to_string(data_OK[['ExternalServiceName','Процент ОК', 'Процент ERROR','Процент TIMEOUT']])
    formatted_table1 = format_dataframe_to_string(data_time)

    await message.answer(formatted_table0, parse_mode=ParseMode.HTML)
    await message.answer(formatted_table1, parse_mode=ParseMode.HTML)


@dp.message(Command('tasklist'))
async def echo_handler(message: Message) -> None:
    try:
        containers = docker_client.containers.list()
        lines = [f"{c.name}  {c.status}" for c in containers]
        await message.answer("<pre>" + "\n".join(lines) + "</pre>", parse_mode=ParseMode.HTML)
    except TypeError:
        await message.answer("Nice cock!")

@dp.message(Command('start_consoles'))
async def start_consoles(message):
    try:
        for name in DOCKER_CONTAINERS:
            try:
                container = docker_client.containers.get(name)
                if container.status != 'running':
                    container.start()
                    await message.answer(f"{name} запущен")
                else:
                    await message.answer(f"{name} уже работает")
            except docker.errors.NotFound:
                await message.answer(f"Контейнер {name} не найден")
            except Exception as e:
                await message.answer(f"Ошибка при запуске {name}: {e}")
    except Exception as e:
        await message.answer(f"Глобальная ошибка: {e}")

# перезапуск моделек
@dp.message(Command('restart_consoles'))
async def restart_consoles(message):
    try:
        for name in DOCKER_CONTAINERS:
            try:
                container = docker_client.containers.get(name)
                container.restart()
                await message.answer(f"{name} перезапущен")
            except docker.errors.NotFound:
                await message.answer(f"Контейнер {name} не найден")
            except Exception as e:
                await message.answer(f"Ошибка при перезапуске {name}: {e}")
    except Exception as e:
        await message.answer(f"Глобальная ошибка: {e}")


@dp.message(Command('ping'))
async def send_pong(message):
    pong=""
    hostname0='192.168.20.81'
    hostname1='192.168.20.82'
    response = os.system('ping ' + hostname0)
    response1 = os.system('ping ' + hostname1)
    if (response == 0)&(response1 == 0):
        pong=(str(hostname0)+' & ' +str(hostname1)+' is up')

    elif (response == 0)&(response1 != 0):
        pong = (str(hostname0) + ' is up'+' & '+str(hostname1) + ' is down')

    elif (response != 0)&(response1 == 0):
        pong = (str(hostname0) + ' is down'+' & '+str(hostname1) + ' is up')

    else:
        pong=( str(hostname0)+' & ' +str(hostname1)+' is down')

    await message.reply(pong)

#проверка работы моделей
@dp.message(Command('check'))
async def check_anyway(message):
    s = crash_process()
    if s:
        try:
            await message.answer(text="Упали контейнеры:")
            for i in range(len(s)):
                await message.answer(text=s[i].to_string())
        except Exception as e:
            print(e)
    else: await message.answer(text="Все работает")


def exec_cmd(command):
    try:
        sub_ = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        subprocess_return = sub_.stdout.read()
        return subprocess_return
    except:
        return "Nice cock!"



"""------------------рассылка-------------------------"""

async def report0():
    data_OK, data_time =services()

    # df в форматированную строку
    def format_dataframe_to_string(df):
        table_string = df.to_string(index=False)
        return f"<pre>{table_string}</pre>"

    formatted_table0 = format_dataframe_to_string(data_OK.loc[data_OK['Процент ОК']<90][['ExternalServiceName','Процент ОК','Процент TIMEOUT']])
    formatted_table1 = format_dataframe_to_string(data_time.loc[data_time.avg_sec>data_time.avg_sec_month])

    if data_OK.loc[data_OK['Процент ОК']<90].shape[0] != 0:
        for user in users_for_send:
            try:
                await bot.send_message(chat_id=user, text=formatted_table0)
                await bot.send_message(chat_id=user, text=formatted_table1)
            except Exception as e:
                print(e)
    else:
        for user in users_for_send:
            try:
                await bot.send_message(chat_id=user, text=f"Нет задержек по сервисам")
            except Exception as e:
                print(e)

    text0, text1 = pdn_for_report()
    for user in users_for_send:
        try:
            await bot.send_message(chat_id=user, text=text1)
            await bot.send_message(chat_id=user, text=text0)
        except Exception as e:
            print(e)


#попытка репортинга коллекторов
async def report1():
    df = collector_calls()
    if df.shape[0] > 1:
        for user in users_for_calls_send:
            try:
                await bot.send_message(chat_id=user, text=f"Звонки с нарушениями за вчера")
                for i in range(df.shape[0]):
                    await bot.send_message(chat_id=user, text=df.loc[i].to_string())
                    await bot.send_message(chat_id=user, text=f"--------------------")
            except Exception as e:
                print(e)

    elif df.shape[0] == 1:
        for user in users_for_calls_send:
            try:
                print(user)
                await bot.send_message(chat_id=user, text=f"Звонок с нарушениями за вчера")
                await bot.send_message(chat_id=user, text=df.loc[0].to_string())
            except Exception as e:
                print(e)
    else:
        for user in users_for_calls_send:
            try:
                print(user)
                await bot.send_message(chat_id=user, text=f"Нет звонков с нарушениями за вчера")
            except Exception as e:
                print(e)

#проверка не упалили консоли
async def check():
    s = crash_process()
    if s:
        try:
            await bot.send_message(chat_id=505568035, text=f"Упали контейнеры")
            for i in s:
                await bot.send_message(chat_id=505568035, text=i.to_string())
        except Exception as e:
            print(e)




async def main() -> None:
    user_logger.info(f"Старт бота. Начальное состояние: users={users}, users_for_send={users_for_send}, "
                     f"save_users_for_send={save_users_for_send}, users_for_calls_send={users_for_calls_send}, "
                     f"save_users_for_calls_send={save_users_for_calls_send}")

    # диспетчеризация событий запуска
    scheduler = AsyncIOScheduler()
    timezone="Europe/Moscow"

    scheduler.add_job(report0, trigger="cron", hour=10, minute=00, start_date=datetime.now())
    scheduler.add_job(report1, trigger="cron", hour=10, minute=10, start_date=datetime.now())
    #scheduler.add_job(check, "interval", minutes=30)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
    gc.collect()

