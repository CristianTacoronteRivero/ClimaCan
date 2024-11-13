"""
Script que se encarga de leer el fichero CSV donde contiene todos los metadatos de las estaciones
y registra uno a uno la última observacion de cada estacion en un servidor InfluxDB.
"""

from pathlib import Path
from typing import Dict, List

import pandas as pd
from ctrutils.handlers.LoggingHandlerBase import LoggingHandler

from conf import GRAFCAN__CSV_FILE_CLASSES_METADATA_STATIONS
from conf import GRAFCAN__LOG_FILE_SCRIPT_WRITE_LAST_OBSERVATIONS as LOG_FILE
from conf import GRAFCAN_DATABASE_NAME
from conf import INFLUXDB_CLIENT as client
from conf import LOG_BACKUP_PERIOD, LOG_RETENTION_PERIOD
from src.common.functions import normalize_text
from src.grafcan.classes.Exceptions import DataFetchError
from src.grafcan.classes.FetchObservationsLast import FetchObservationsLast

# Configurar logger
handler = LoggingHandler(
    log_file=LOG_FILE,
    log_backup_period=LOG_BACKUP_PERIOD,
    log_retention_period=LOG_RETENTION_PERIOD,
)
LOGGER = handler.configure_logger()

# Crear el objeto FetchObservationsLast
fetcher = FetchObservationsLast()


def read_stations_csv(csv_file: Path) -> pd.DataFrame:
    """
    Lee un archivo CSV y lo convierte en un DataFrame de Pandas.

    :param csv_file: Ruta del archivo CSV.
    :type csv_file: Path
    :return: DataFrame de Pandas con los datos del archivo CSV.
    :rtype: pd.DataFrame
    """
    LOGGER.info(f"Leyendo archivo CSV desde {csv_file}")
    df = pd.read_csv(csv_file).set_index("things_id")
    df.sort_index(inplace=True)
    LOGGER.info(f"Archivo CSV leido correctamente, {len(df)} estaciones cargadas.")
    return df


def normalize_measurement(text: str) -> str:
    """
    Normaliza el texto eliminando caracteres especiales y espacios en blanco y mayúsculas.

    :param text: Texto a normalizar.
    :type text: str
    :return: Texto normalizado.
    :rtype: str
    """
    text = normalize_text(text)
    return (
        text.replace(" ", "_")
        .replace(",", "")
        .lower()
        .replace("(", "")
        .replace(")", "")
    )


def add_features_to_points(points: List[Dict], measurement: str) -> List[Dict]:
    """
    Agrega clave measurement a cada diccionario y elimina claves en "fields" con valores nulos.

    :param points: Lista de diccionarios con datos de la estación.
    :type points: List[Dict]
    :param measurement: Nombre del tipo de medición.
    :type measurement: str
    :return: Lista de diccionarios con la clave measurement y sin claves nulas.
    :rtype: List[Dict]
    """
    # Agregar clave measurement a cada diccionario y eliminar claves en "fields" con valores nulos
    valid_points = []
    # Agregar clave measurement a cada diccionario y eliminar toda clave que contenga valor nulo
    for point in points:
        # Agregar measurement
        point["measurement"] = measurement

        # Crear lista de claves a eliminar en el caso de que sean nulos sus valores
        keys_to_remove = [
            key for key, value in point["fields"].items() if value is None
        ]
        for key in keys_to_remove:
            del point[key]

        # Comprobar si "fields" tiene al menos un valor; si es asi, agregar a los puntos válidos
        if point["fields"]:
            valid_points.append(point)

    # Solo devolver puntos con "fields" no vacios
    return valid_points


if __name__ == "__main__":
    LOGGER.info("Inicio del proceso de registro de observaciones en InfluxDB.")

    # Leer el DataFrame de los metadatos de las estaciones
    df_stations = read_stations_csv(GRAFCAN__CSV_FILE_CLASSES_METADATA_STATIONS)

    # Recorrer cada fila para obtener el indice y los metadatos de cada estacion
    for index, row in df_stations.iterrows():
        LOGGER.info(f"Procesando estacion con ID '{index}'.")

        try:
            # Obtener la observacion más reciente de la estacion correspondiente
            last_observation = fetcher.fetch_last_observation(index)
            # Obtener diccionario de metadatos de la estacion
            station_metadata = row.to_dict()
            # Obtener measurement para esta estacion a partir del nombre de la localizacion
            measurement = normalize_measurement(station_metadata["locations_name"])
            # Agregar el measurement a cada diccionario de la lista de puntos y eliminar los valores nulos
            data_points = add_features_to_points(last_observation, measurement)

            LOGGER.info(
                f"Registrando observacion en measurement '{measurement}' para estacion con ID '{index}'."
            )

            # Registrar datos en el servidor InfluxDB
            client.write_points(
                database=GRAFCAN_DATABASE_NAME,
                points=data_points,
                tags=station_metadata,
            )
            LOGGER.info(
                f"Observacion registrada correctamente en InfluxDB para measurement '{measurement}'."
            )

        except DataFetchError as e:
            LOGGER.error(f"Error al obtener datos para la estacion con ID '{index}': '{e}'")
            continue  # Continuar con la siguiente estacion en caso de error de obtencion de datos
        except Exception as e:
            LOGGER.error(
                f"Error inesperado al procesar la estacion con ID '{index}': '{e}'"
            )
            continue  # Continuar con la siguiente estacion en caso de error general

    LOGGER.info("Proceso de registro de observaciones completado.\n")
