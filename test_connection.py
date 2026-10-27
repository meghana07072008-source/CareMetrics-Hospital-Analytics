
import mysql.connector
from config import DB_CONFIG

try:
    connection = mysql.connector.connect(**DB_CONFIG)

    if connection.is_connected():
        print("MySQL connection successful!")

        cursor = connection.cursor()

        cursor.execute("SHOW TABLES")

        print("\nTables in hospital_analysis:")

        for table in cursor.fetchall():
            print(table[0])

        cursor.close()
        connection.close()

except mysql.connector.Error as error:
    print("MySQL connection failed!")
    print("Error:", error)
