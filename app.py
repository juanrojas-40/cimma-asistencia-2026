import streamlit as st
import pandas as pd
import io

# Define score ranges for each test type.
# These are example ranges. You must replace them with the official PAES score conversion tables.
SCORE_RANGES = {
    "CLE8": {  # Comprensión Lectora
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
    },
    "M1E8": {  # Matemática 1
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
        65: 750,  # For M1 which has 65 questions
    },
    "M2E8": {  # Matemática 2 (Example, adjust as needed)
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
        65: 750,
    },
    "CFE8": {  # Física
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
    },
    "CBE8": {  # Biología
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
    },
    "CQE8": {  # Química
        0: 150,
        10: 200,
        20: 300,
        30: 400,
        40: 500,
        50: 600,
        60: 700,
    },
}

def get_paes_score(correct_answers, test_type):
    """Convert number of correct answers to PAES score using the defined ranges."""
    if test_type not in SCORE_RANGES:
        return None

    ranges = SCORE_RANGES[test_type]
    # Sort the keys to find the correct range
    keys = sorted(ranges.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= correct_answers < keys[i + 1]:
            return ranges[keys[i]]
    # If correct_answers is equal to or greater than the last key
    if correct_answers >= keys[-1]:
        return ranges[keys[-1]]
    return ranges[0]  # Default to the lowest score if below all ranges

def process_file(uploaded_file, date_uploaded):
    """Process a single uploaded CSV file."""
    try:
        df = pd.read_csv(uploaded_file)
        st.success(f"Archivo '{uploaded_file.name}' cargado exitosamente.")

        # Determine test type from Quiz Name
        quiz_name = df['Quiz Name'].iloc[0] if 'Quiz Name' in df.columns else ""
        test_type = "UNKNOWN"
        if "CLE8" in quiz_name:
            test_type = "CLE8"
        elif "M1E8" in quiz_name:
            test_type = "M1E8"
        elif "M2E8" in quiz_name:
            test_type = "M2E8"
        elif "CFE8" in quiz_name:
            test_type = "CFE8"
        elif "CBE8" in quiz_name:
            test_type = "CBE8"
        elif "CQE8" in quiz_name:
            test_type = "CQE8"

        # Extract relevant columns
        required_cols = ['ZipGrade ID', 'First Name', 'Last Name']
        for col in required_cols:
            if col not in df.columns:
                st.error(f"La columna '{col}' no se encuentra en el archivo '{uploaded_file.name}'.")
                return None

        # Find all Q columns (Q1, Q2, ..., QN)
        q_columns = [col for col in df.columns if col.startswith('Q') and col[1:].isdigit()]
        q_columns.sort(key=lambda x: int(x[1:]))  # Sort by question number

        # Calculate total correct answers for each student
        df['Total Correct'] = df[q_columns].sum(axis=1)

        # Map to PAES score
        df['PAES Score'] = df['Total Correct'].apply(lambda x: get_paes_score(x, test_type))

        # Add date uploaded
        df['Date Uploaded'] = date_uploaded

        # Keep only necessary columns
        final_cols = ['ZipGrade ID', 'First Name', 'Last Name', 'Total Correct', 'PAES Score', 'Date Uploaded']
        df_final = df[final_cols]

        st.write("Vista previa de los datos procesados:")
        st.dataframe(df_final.head())

        return df_final, test_type

    except Exception as e:
        st.error(f"Error al procesar el archivo '{uploaded_file.name}': {e}")
        return None, None

# --- Streamlit App ---
st.title("📊 Sistema de Registro y Reporte de Resultados PAES")

st.markdown("""
Bienvenido al sistema para cargar y procesar resultados de ensayos PAES.
Suba uno o varios archivos CSV correspondientes a los ensayos de:
- **Comprensión Lectora (CL)**
- **Matemática 1 (M1)**
- **Matemática 2 (M2)**
- **Física (CF)**
- **Biología (CB)**
- **Química (CQ)**

El sistema calculará la puntuación PAES para cada estudiante y preparará los datos para su envío por correo electrónico.
""")

# Upload files
uploaded_files = st.file_uploader(
    "Seleccione los archivos CSV de los ensayos PAES",
    type=["csv"],
    accept_multiple_files=True,
    help="Puede subir múltiples archivos a la vez."
)

# Input for upload date
upload_date = st.date_input("Fecha de Subida", value=None)

# Process button
if st.button("Procesar Archivos") and uploaded_files and upload_date:
    all_data = []  # List to store DataFrames for each file

    for uploaded_file in uploaded_files:
        df_processed, test_type = process_file(uploaded_file, upload_date)
        if df_processed is not None:
            all_data.append((df_processed, test_type))

    if all_data:
        # Combine all processed data into a single DataFrame
        combined_df = pd.concat([df for df, _ in all_data], ignore_index=True)
        st.success(f"✅ Se han procesado {len(all_data)} archivos con éxito.")

        # Display summary
        st.subheader("Resumen de Datos Procesados")
        st.dataframe(combined_df)

        # Prepare data for Google Sheets (Placeholder)
        st.info("ℹ️ Los datos están listos para ser registrados en Google Sheets.")
        # TODO: Implement gspread to write `combined_df` to Google Sheets here.
        # Example: worksheet.update([combined_df.columns.values.tolist()] + combined_df.values.tolist())

        # Prepare data for Email (Placeholder)
        st.info("ℹ️ Los datos están listos para ser enviados por correo electrónico a los apoderados.")
        # TODO: Implement smtplib to send emails to guardians.
        # You will need to map ZipGrade ID to guardian email addresses.

        # Option to download the processed data
        csv_buffer = io.StringIO()
        combined_df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Descargar Datos Procesados como CSV",
            data=csv_buffer.getvalue(),
            file_name=f"resultados_paes_{upload_date}.csv",
            mime="text/csv",
        )

elif uploaded_files and not upload_date:
    st.warning("⚠️ Por favor, seleccione una fecha de subida antes de procesar los archivos.")

elif not uploaded_files and upload_date:
    st.warning("⚠️ Por favor, suba al menos un archivo CSV para procesar.")

else:
    st.info("ℹ️ Por favor, suba los archivos CSV y seleccione la fecha de subida.")

# Footer
st.markdown("---")
st.caption("Este sistema está diseñado para facilitar el registro y reporte de resultados PAES.")