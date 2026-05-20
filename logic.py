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

# получение логов контейнеров
def get_container_logs(container_name, lines=50):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        
        logs = container.logs(tail=lines).decode('utf-8')
        
        return {
            'name': container.name,
            'status': container.status,
            'logs': logs
        }
    except docker.errors.NotFound:
        return {
            'name': container_name,
            'status': 'not_found',
            'logs': f"Контейнер {container_name} не найден"
        }
    except Exception as e:
        return {
            'name': container_name,
            'status': 'error',
            'logs': f"Ошибка при получении логов: {str(e)}"
        }
        
# выгрузка заявок
def new_data():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    data = pd.read_sql_query("""select top(5)* from dms..Output_vector_ml with(nolock) order by created desc""", engine)
    return data

# выгружаем ошибки по звонкам
def collector_calls():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(text("""
           declare @dtStart date, @dtEnd date 
    set @dtStart = cast(getdate()-1 as date)
    set @dtEnd = cast(getdate() as date) ; 

    WITH holidays AS (
        SELECT CAST('2024-12-30' AS DATE) AS holiday
        UNION ALL SELECT CAST('2024-12-31' AS DATE)
        UNION ALL SELECT CAST('2025-01-01' AS DATE)
        UNION ALL SELECT CAST('2025-01-02' AS DATE)
        UNION ALL SELECT CAST('2025-01-03' AS DATE)
        UNION ALL SELECT CAST('2025-01-04' AS DATE)
        UNION ALL SELECT CAST('2025-01-05' AS DATE)
        UNION ALL SELECT CAST('2025-01-06' AS DATE)
        UNION ALL SELECT CAST('2025-01-07' AS DATE)
        UNION ALL SELECT CAST('2025-01-08' AS DATE)
    ),
    calls_with_local_time AS (
        SELECT
            ph.dwh_person_id, 
            ph.phone_number,
            typ.name typeName, 
            de.contract,
            de.gmt, 
            ca.TimeStart, 
            ca.DurationTalk, 
            ca.AbonentName,
            -- Корректируем время звонка на разницу с Москвой (UTC+3)
            DATEADD(
            HOUR, 
            ISNULL(TRY_CAST(SUBSTRING(de.gmt, 4, LEN(de.gmt)) AS INT), 0) - 3, 
            ca.TimeStart
        ) AS LocalTime
        FROM DWH.[dbo].DWH_PHONE ph (nolock)
        join DWH.[dbo].[DWH_PHONE_TYP] typ on typ.id = ph.typ
        JOIN [DWH].[dbo].[DWH_DEBT] de (nolock) ON ph.dwh_person_id = de.dwh_person_id
        join (
            select pa.Title, cast(lg.dtInsert as date) dt from Billing..LogPayments lg (nolock)
            join Billing..PersonalAccounts pa (nolock) on lg.ClientId = pa.ClientId
            where lg.AmountDelay > 0 and lg.dtInsert between @dtStart and @dtEnd
                ) lgg on lgg.Title = de.contract
        JOIN [Infinity].[dbo].[S_Calls] ca (nolock) ON ca.AbonentNumber = ph.phone_number and cast(ca.TimeStart as date) = lgg.dt
        WHERE ca.TimeStartDate BETWEEN @dtStart AND @dtEnd and de.gmt not like '%/%'
            AND ca.AbonentName IS NOT NULL
            AND ca.DurationTalk > 0
            AND ca.AbonentNumber not in ('', '79999999999')
            and ph.typ = 1
            and de.channel not in ('BNPL MK-Mobile')
    )
    SELECT
        --c.dwh_person_id, 
        c.phone_number,
       -- c.typeName, 
        c.contract,
        c.gmt, 
        c.TimeStart, 
        c.LocalTime, 
        --c.DurationTalk, 
        c.AbonentName,
        CASE 
            WHEN DATEPART(WEEKDAY, c.LocalTime) IN (1, 7) OR h.holiday IS NOT NULL 
                THEN 'Weekend/Holiday' 
            ELSE 'Weekday' 
        END AS DayType
    FROM calls_with_local_time c
    LEFT JOIN holidays h ON CAST(c.LocalTime AS DATE) = h.holiday
    WHERE (
        -- Проверка на будни (Понедельник - Пятница)
        (DATEPART(WEEKDAY, c.LocalTime) BETWEEN 2 AND 6 AND 
            (DATEPART(HOUR, c.LocalTime) < 8 OR DATEPART(HOUR, c.LocalTime) >= 22))
        -- Проверка на выходные и праздничные дни
        OR
        ((DATEPART(WEEKDAY, c.LocalTime) IN (1, 7) OR h.holiday IS NOT NULL) 
            AND (DATEPART(HOUR, c.LocalTime) < 9 OR DATEPART(HOUR, c.LocalTime) >= 20))
    )
    order by c.TimeStart desc
    OPTION (MAXDOP 4)
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
select
    cast(isnull((
select sum([Сумма кредита ЦБ]) sum_high_pdn
from
    RISK_REPORT.dbo.MPL_new with(nolock)
where
    cast(DATEADD(DD,-3,GETDATE()) as date) <= dtStart
 and pdn_pl > 0.8
 and selfEmployed_credit = 0
),0)
/
(
select
    sum([Сумма кредита ЦБ]) sum_high_pdn
from
    RISK_REPORT.dbo.MPL_new with(nolock)
where
    cast(DATEADD(DD,-3,GETDATE() ) as date) <= dtStart
 and selfEmployed_credit = 0
) as real)
""", engine)
    pdn_80=pdn80.values[0][0]

    return round(pdn_80, 5).astype(float)

def PDN_50_80():
    conn_str = f"mssql+pyodbc://{log}:{psw}@{host}/Billing?driver={DRIVER_NAME}"
    engine = create_engine(conn_str)
    pdn50 = pd.read_sql_query("""select
    cast(isnull((
select sum([Сумма кредита ЦБ]) sum_high_pdn
from
    RISK_REPORT.dbo.MPL_new with(nolock)
where
    cast(DATEADD(DD,-3,GETDATE()) as date) <= dtStart
 and pdn_pl <= 0.8 
 and pdn_pl >= 0.5 
 and selfEmployed_credit = 0
),0)
/
(
select
    sum([Сумма кредита ЦБ]) sum_high_pdn
from
    RISK_REPORT.dbo.MPL_new with(nolock)
where
    cast(DATEADD(DD,-3,GETDATE() ) as date) <= dtStart
 and selfEmployed_credit = 0
) as real)
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
            data_OK = pd.read_sql_query("""DECLARE @dt DATE = DATEADD(DAY, -1, GETDATE())

    SELECT 
        [Дата заявки],
        ExternalServiceName,
        COUNT(DISTINCT id) AS 'Кол-во заявок',
        ROUND(100.0 * SUM(CASE WHEN Status_pl = 'OK' THEN 1 ELSE 0 END) / COUNT(DISTINCT id), 1) AS 'Процент ОК',
        ROUND(100.0 * SUM(CASE WHEN Status_pl = 'ERROR' THEN 1 ELSE 0 END) / COUNT(DISTINCT id), 1) AS 'Процент ERROR',
        ROUND(100.0 * SUM(CASE WHEN Status_pl = 'TIMEOUT' THEN 1 ELSE 0 END) / COUNT(DISTINCT id), 1) AS 'Процент TIMEOUT'
    FROM (
        -- Основные внешние сервисы
        SELECT 
            a.id,
            CAST(a.dtInput AS DATE) AS [Дата заявки],
            es.Name AS ExternalServiceName,
            CASE 
                WHEN sr.ExternalServiceId = 35 AND (sr.Comment = 'SCR: Empty response recieved' OR sr.Status = -1 OR sr.status = 1) 
                    THEN CASE WHEN mb.isError = 0 THEN 'OK' ELSE 'ERROR' END
                WHEN sr.Comment = 'SCR: Empty response recieved' OR sr.Status = -1 OR sr.status = 1 THEN 'ERROR' 
                WHEN sr.Status = 2 THEN 'OK' 
                WHEN sr.Status = 3 THEN 'TIMEOUT' 
            END AS Status_pl,
            ROW_NUMBER() OVER (PARTITION BY a.id, sr.ExternalServiceId ORDER BY sr.StatusTime DESC) AS rn
        FROM Billing..Applications a
        INNER JOIN pl_int.scr.SolutionQueue sq ON a.id = sq.OrderId
        INNER JOIN pl_int.scr.SolutionRequest sr ON sq.id = sr.SolutionId
        INNER JOIN pl_int.scr.ExternalServices es ON sr.ExternalServiceId = es.id
        LEFT JOIN (
            SELECT AppId, ISNULL(isError, 1) as isError
            FROM mobileScoringService..Request req
            LEFT JOIN mobileScoringService..Response res ON res.Id = req.ResponseId
        ) mb ON a.id = mb.AppId
        WHERE a.dtInput BETWEEN '2024-01-01' AND GETDATE()

        UNION ALL

        -- Самозанятые через Camunda
        SELECT 
            sq.OrderId AS id,
            CAST(a.dtInput AS DATE) AS [Дата заявки],
            'Статус самозанятого' AS ExternalServiceName,
            CASE WHEN DATEDIFF(MILLISECOND, sb.StartTime, sb.EndTime) < 15000 THEN 'OK' ELSE 'TIMEOUT' END AS Status_pl,
            1 AS rn
        FROM pl_int.scr.SolutionBenchmarks sb
        INNER JOIN pl_int.scr.StrategyNodes sn ON sn.id = sb.StrategyNodeId
        INNER JOIN pl_int.scr.SolutionQueue sq ON sq.id = sb.SolutionId
        INNER JOIN Billing..Applications a ON a.id = sq.OrderId
        WHERE sn.dsc = ' Camunda call(Самозанятый)' 
            AND sq.CreateTime >= '2024-01-01'  -- Исправлена дата (была 2025)
    ) AS combined_data
    WHERE rn = 1 
        AND [Дата заявки] = @dt
    GROUP BY [Дата заявки], ExternalServiceName
            """, conn)
            data_time = pd.read_sql_query("""DECLARE @requests_number INT = 10
        DECLARE @yesterday DATE = CAST(DATEADD(DD, -1, GETDATE()) AS DATE)
        DECLARE @last_month_end DATE = CAST(EOMONTH(DATEADD(MONTH, -1, GETDATE())) AS DATE)

        SELECT 
        yr.ExternalService,
        ROUND(AVG(yr.AvgSeconds1), 3) AS avg_sec,
        ma.avg_sec_month
        FROM (
        SELECT 
            r.ExternalService,
            r.AvgSeconds1,
            ROW_NUMBER() OVER (PARTITION BY r.ExternalService ORDER BY r.orderid DESC) AS n_req
        FROM (
            SELECT 
                p_s.*,
                CASE 
                    WHEN p_s.ExternalService = 'NBKI' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 5 
                    WHEN p_s.ExternalService = 'NalogRu' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 5 
                    WHEN p_s.ExternalService = 'BankruptService' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 2 
                    WHEN p_s.ExternalService = 'Facecloud' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 2 
                    ELSE p_s.AvgSeconds 
                END AS AvgSeconds1
            FROM [Risk_report].dbo.proccesing_service p_s WITH(NOLOCK)
            WHERE p_s.dt >= '20230101' 
                AND NOT (
                    p_s.dt_month = '20231031' 
                    AND p_s.Checks = 'AutoApprove' 
                    AND p_s.channel = 'Аэрофлот' 
                    AND p_s.ExternalService = 'Juicy'
                )
        ) r
        WHERE r.dt = @yesterday
        ) yr
        INNER JOIN (
        SELECT 
            r.ExternalService,
            ROUND(AVG(r.AvgSeconds1), 3) AS avg_sec_month
        FROM (
            SELECT 
                p_s.*,
                CASE 
                    WHEN p_s.ExternalService = 'NBKI' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 5 
                    WHEN p_s.ExternalService = 'NalogRu' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 5 
                    WHEN p_s.ExternalService = 'BankruptService' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 2 
                    WHEN p_s.ExternalService = 'Facecloud' AND p_s.dt_month = '20231031' AND p_s.AvgSeconds > 10 THEN 2 
                    ELSE p_s.AvgSeconds 
                END AS AvgSeconds1
            FROM [Risk_report].dbo.proccesing_service p_s WITH(NOLOCK)
            WHERE p_s.dt >= '20230101' 
                AND NOT (
                    p_s.dt_month = '20231031' 
                    AND p_s.Checks = 'AutoApprove' 
                    AND p_s.channel = 'Аэрофлот' 
                    AND p_s.ExternalService = 'Juicy'
                )
        ) r
        WHERE r.dt >= DATEADD(MONTH, -1, @last_month_end) 
            AND r.dt <= @last_month_end
        GROUP BY r.ExternalService
        ) ma ON yr.ExternalService = ma.ExternalService
        WHERE yr.n_req <= @requests_number
        AND yr.ExternalService IN (
            SELECT ExternalService
            FROM (
                SELECT 
                    r.ExternalService,
                    ROW_NUMBER() OVER (PARTITION BY r.ExternalService ORDER BY r.orderid DESC) AS n_req
                FROM (
                    SELECT 
                        p_s.ExternalService,
                        p_s.orderid
                    FROM [Risk_report].dbo.proccesing_service p_s WITH(NOLOCK)
                    WHERE p_s.dt >= '20230101' 
                        AND NOT (
                            p_s.dt_month = '20231031' 
                            AND p_s.Checks = 'AutoApprove' 
                            AND p_s.channel = 'Аэрофлот' 
                            AND p_s.ExternalService = 'Juicy'
                        )
                        AND p_s.dt = @yesterday
                ) r
            ) counter
            WHERE counter.n_req >= @requests_number
            GROUP BY counter.ExternalService
        )
        GROUP BY yr.ExternalService, ma.avg_sec_month
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


