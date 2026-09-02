from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import pandas as pd


MARGEN = 30
ALTURA_HEADER = 110
ALTURA_TITULO = 60
ALTURA_FOOTER = 36

PADDING_CELDA_H = 14   # relleno horizontal a cada lado del texto en cada celda
PADDING_CELDA_V = 10   # relleno vertical a cada lado del texto en cada celda
ANCHO_MINIMO_COLUMNA = 60

COLOR_HEADER_TABLA = (31, 59, 87)       # #1f3b57, igual al AgGrid
COLOR_TEXTO_HEADER = (255, 255, 255)
COLOR_FILA_PAR = (255, 255, 255)
COLOR_FILA_IMPAR = (242, 245, 248)
COLOR_TEXTO = (30, 30, 30)
COLOR_VERDE = (46, 125, 50)
COLOR_AMARILLO = (249, 168, 37)
COLOR_ROJO = (198, 40, 40)

# Si no tienes estas fuentes, se cae a la fuente por defecto de Pillow (más fea, pero funciona)
RUTA_FUENTE_BOLD = Path(__file__).parent / "fonts" / "Montserrat-Bold.ttf"
RUTA_FUENTE_REGULAR = Path(__file__).parent / "fonts" / "Montserrat-Regular.ttf"


def _cargar_fuente(ruta: Path, tamano: int):
    try:
        return ImageFont.truetype(str(ruta), tamano)
    except Exception:
        return ImageFont.load_default()

def _interpolar_color(color1, color2, factor):
    factor = max(0.0, min(1.0, factor))
    return tuple(int(c1 + (c2 - c1) * factor) for c1, c2 in zip(color1, color2))

def _color_semaforo_relativo(valor: float, minimo: float, maximo: float):
    """Escala de color tipo Excel: rojo (mínimo) -> amarillo (medio) -> verde (máximo),
    calculada sobre el rango de valores que realmente vienen en 'resumen' (ya filtrados)."""
    if maximo == minimo:
        return COLOR_AMARILLO
 
    punto_medio = (minimo + maximo) / 2
 
    if valor <= punto_medio:
        rango = punto_medio - minimo
        factor = (valor - minimo) / rango if rango else 1.0
        return _interpolar_color(COLOR_ROJO, COLOR_AMARILLO, factor)
    else:
        rango = maximo - punto_medio
        factor = (valor - punto_medio) / rango if rango else 1.0
        return _interpolar_color(COLOR_AMARILLO, COLOR_VERDE, factor)


def _formato_moneda(valor: float) -> str:
    return f"$ {int(valor):,}".replace(",", ".")


def _texto_celda(clave: str, valor) -> str:
    if clave == "Valor_Promesas":
        return _formato_moneda(valor)
    if isinstance(valor, (int, float)):
        return f"{valor:,}".replace(",", ".")
    return str(valor)


def _medir(draw, texto, font):
    bbox = draw.textbbox((0, 0), texto, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[1]


def _y_centrado(draw, y_inicio, alto_contenedor, texto, font):
    bbox = draw.textbbox((0, 0), texto, font=font)
    alto_texto = bbox[3] - bbox[1]
    return y_inicio + (alto_contenedor - alto_texto) / 2 - bbox[1]


def generar_imagen_productividad(
    resumen: pd.DataFrame,
    col_asesor: str,
    hora_actualiz: str,
    ruta_logo_izq: str = "scripts/image/Elite_H_color.png",
    ruta_logo_der: str = "scripts/image/baguer_logo.png",
    titulo: str = "Productividad x Asesor - Campaña BAGUER",
) -> Image.Image:
    filas = resumen.reset_index(drop=True)

    columnas = [
        (col_asesor, "Nombre Asesor"),
        ("Cuentas_Gestionadas", "Cuentas"),
        ("Cantidad_Promesas", "Promesas"),
        ("Valor_Promesas", "Valor Promesas"),
    ]

    fuente_titulo = _cargar_fuente(RUTA_FUENTE_BOLD, 20)
    fuente_encabezado = _cargar_fuente(RUTA_FUENTE_BOLD, 16)
    fuente_celda = _cargar_fuente(RUTA_FUENTE_REGULAR, 15)
    fuente_footer = _cargar_fuente(RUTA_FUENTE_REGULAR, 14)

    # --- Imagen/draw temporal SOLO para medir texto (no se dibuja nada aquí) ---
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    # --- Calcular ancho de cada columna y alto de fila según el contenido real ---
    anchos_columna = {}
    alto_texto_max_celda = 0
    for clave, etiqueta in columnas:
        ancho_max, alto_h, _ = _medir(medidor, etiqueta, fuente_encabezado)
        for _, fila in filas.iterrows():
            texto = _texto_celda(clave, fila[clave])
            ancho_texto, alto_texto, _ = _medir(medidor, texto, fuente_celda)
            ancho_max = max(ancho_max, ancho_texto)
            alto_texto_max_celda = max(alto_texto_max_celda, alto_texto)
        anchos_columna[clave] = max(ancho_max + PADDING_CELDA_H * 2, ANCHO_MINIMO_COLUMNA)

    ancho_tabla = sum(anchos_columna.values())

    alto_texto_encabezado = max(_medir(medidor, etq, fuente_encabezado)[1] for _, etq in columnas)
    altura_encabezado_tabla = alto_texto_encabezado + PADDING_CELDA_V * 2
    altura_fila = (alto_texto_max_celda if alto_texto_max_celda else 15) + PADDING_CELDA_V * 2

    ancho_texto_titulo, _, _ = _medir(medidor, titulo, fuente_titulo)
    ancho_titulo_total = ancho_texto_titulo + MARGEN * 2

    ANCHO = int(max(ancho_tabla + MARGEN * 2, ancho_titulo_total))

    alto_total = int(
        MARGEN * 2
        + ALTURA_HEADER
        + ALTURA_TITULO
        + altura_encabezado_tabla
        + altura_fila * len(filas)
        + ALTURA_FOOTER
    )

    # --- Crear el lienzo final ya con las medidas correctas ---
    imagen = Image.new("RGB", (ANCHO, alto_total), "white")
    draw = ImageDraw.Draw(imagen)

    y = MARGEN

    # --- Logos (tamaño relativo al ancho ya calculado) ---
    try:
        logo_izq = Image.open(ruta_logo_izq).convert("RGBA")
        logo_izq.thumbnail((int(ANCHO * 0.30), ALTURA_HEADER))
        imagen.paste(logo_izq, (MARGEN, y), logo_izq)
    except Exception:
        pass

    try:
        logo_der = Image.open(ruta_logo_der).convert("RGBA")
        logo_der.thumbnail((int(ANCHO * 0.25), ALTURA_HEADER))
        imagen.paste(logo_der, (ANCHO - MARGEN - logo_der.width, y), logo_der)
    except Exception:
        pass

    y += ALTURA_HEADER

    # --- Título ---
    y_texto = _y_centrado(draw, y, ALTURA_TITULO, titulo, fuente_titulo)
    x_texto = (ANCHO - ancho_texto_titulo) / 2
    draw.text((x_texto, y_texto), titulo, fill=COLOR_TEXTO, font=fuente_titulo)
    y += ALTURA_TITULO

    # --- Tabla centrada horizontalmente ---
    x_inicio_tabla = (ANCHO - ancho_tabla) / 2

    draw.rectangle([x_inicio_tabla, y, x_inicio_tabla + ancho_tabla, y + altura_encabezado_tabla], fill=COLOR_HEADER_TABLA)
    x_actual = x_inicio_tabla
    for clave, etiqueta in columnas:
        ancho_col = anchos_columna[clave]
        y_texto = _y_centrado(draw, y, altura_encabezado_tabla, etiqueta, fuente_encabezado)
        draw.text((x_actual + PADDING_CELDA_H, y_texto), etiqueta, fill=COLOR_TEXTO_HEADER, font=fuente_encabezado)
        x_actual += ancho_col
    y += altura_encabezado_tabla

    for i, fila in filas.iterrows():
        color_fondo = COLOR_FILA_PAR if i % 2 == 0 else COLOR_FILA_IMPAR
        draw.rectangle([x_inicio_tabla, y, x_inicio_tabla + ancho_tabla, y + altura_fila], fill=color_fondo)

        x_actual = x_inicio_tabla
        for clave, etiqueta in columnas:
            ancho_col = anchos_columna[clave]
            valor = fila[clave]
            texto = _texto_celda(clave, valor)

            if clave == "Valor_Promesas":
                color_celda = _color_semaforo_relativo(valor, filas["Valor_Promesas"].min(), filas["Valor_Promesas"].max())
                draw.rectangle(
                    [x_actual + 4, y + 4, x_actual + ancho_col - 4, y + altura_fila - 4],
                    fill=color_celda,
                )
                y_texto = _y_centrado(draw, y, altura_fila, texto, fuente_celda)
                draw.text((x_actual + PADDING_CELDA_H, y_texto), texto, fill="white", font=fuente_celda)
            else:
                y_texto = _y_centrado(draw, y, altura_fila, texto, fuente_celda)
                draw.text((x_actual + PADDING_CELDA_H, y_texto), texto, fill=COLOR_TEXTO, font=fuente_celda)

            x_actual += ancho_col

        y += altura_fila

    # --- Footer ---
    texto_footer = f"Actualizado: {hora_actualiz}"
    ancho_footer, _, _ = _medir(draw, texto_footer, fuente_footer)
    y_texto = _y_centrado(draw, y, ALTURA_FOOTER, texto_footer, fuente_footer)
    draw.text(((ANCHO - ancho_footer) / 2, y_texto), texto_footer, fill=(100, 100, 100), font=fuente_footer)

    return imagen