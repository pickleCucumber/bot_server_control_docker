from sqlalchemy import create_engine, text
import pandas as pd
import re
import subprocess
import json
from dotenv import load_dotenv
import os
import docker

DRIVER_NAME = "ODBC Driver 17 for SQL Server"
load_dotenv()
host = os.getenv("db_host")
psw = os.getenv("db_pass")
log = os.getenv("db_log")


DOCKER_CONTAINERS = [
    'prod_antifraud',
    'prod_nerez',
    'prod_repeated',
    'prod_crimea',
    'prod_all'
]

#мои модельки
def crash_process():
    client = docker.from_env()
    # все контейнеры, с 'prod_' в имени и статус exited
    all_containers = client.containers.list(all=True)
    crashed = []
    for c in all_containers:
        if c.name.startswith('prod_') and c.status == 'exited':
            crashed.append({
                'name': c.name,
                'status': c.status,
                'image': c.image.tags
            })
    return pd.DataFrame(crashed) if crashed else None

# выгрузка заявок
def new_data():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    data = pd.read_sql_query("""select top(5)* from Output_vector_ml with(nolock) order by created desc""", engine)
    return data

# выгружаем ошибки по звонкам
def collector_calls():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(text("""
       
            """), conn)

    except Exception as e:
        print("\nAn error occurred: {0}.".format(str(e)))
    finally:
        conn.close()
    return df

# считаем пдн
def PDN_80():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    pdn80 = pd.read_sql_query("""

""", engine)
    pdn_80=pdn80.values[0][0]

    return round(pdn_80, 5).astype(float)

def PDN_50_80():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    pdn50 = pd.read_sql_query("""
""", engine)
    pdn_50=pdn50.values[0][0]
    return round(pdn_50, 5).astype(float)

def PDN():
    cutoff=0.031
    pdn50=PDN_50_80()
    pdn80=PDN_80()
    return pdn50.astype(float)

def services():

    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    try:
        with engine.connect() as conn:
            data_OK = pd.read_sql_query("""
            """, conn)
            data_time = pd.read_sql_query("""
        """, conn)
    except Exception as e:
        print("\nAn error occurred: {0}.".format(str(e)))

    finally:
        conn.close()
    return data_OK, data_time

def pdn_for_report():
    cutoff=0.03
    cutoff1=0.15

    pdn50 = PDN_50_80()
    pdn80 = PDN_80()
    diff50=round(pdn50-cutoff1, 5)
    diff80=round(pdn80-cutoff, 5)

    if (pdn50>cutoff1)|(pdn50==cutoff1):
        text0 ="PDN50-80 ="+str(round(pdn50*100, 2))+ "% .Превышение на "+str(round(diff50*100, 2))+ " за последние 3 дня"
    else:
        text0 ="PDN50-80 = "+str(round(pdn50*100, 2))+"% . В норме за последние 3 дня"
    if (pdn80>cutoff)|(pdn80==cutoff):
        text ="PDN80+ = "+str(round(pdn80*100, 2))+"% .Превышение на "+str(round(diff80*100, 2))+" за последние 3 дня"
    else:
        text ="PDN80+ = "+str(round(pdn80*100, 2))+"% . В норме за последние 3 дня"
    return text0, text


