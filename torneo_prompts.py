from datetime import datetime, timedelta, timezone
import time
import pandas as pd
from sqlalchemy import text
import streamlit as st
import streamlit.components.v1 as components
from Conexion import obtener_conexion

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA
# ==============================================================================
st.set_page_config(
    page_title='Torneo de Prompts',
    page_icon='🏆',
    layout='centered',
    initial_sidebar_state='collapsed',
)

# Tiempo límite para responder (en minutos)
DURACION_MINUTOS = 5

# Cada cuántos segundos se busca una pregunta activa en la pantalla de espera
ESPERA_SEGUNDOS = 3


# ==============================================================================
# FUNCIONES AUXILIARES
# ==============================================================================
def obtener_fecha_hora_mexico():
    """Retorna fecha y hora actual en zona horaria UTC-6 (Centro de México)."""
    tz_mex = timezone(timedelta(hours=-6))
    ahora = datetime.now(tz_mex)
    return ahora.strftime('%Y-%m-%d'), ahora.strftime('%H:%M:%S')


def ahora_mexico():
    """Retorna el objeto datetime completo (para calcular el temporizador)."""
    return datetime.now(timezone(timedelta(hours=-6)))


# ==============================================================================
# APLICACIÓN PRINCIPAL DEL TORNEO DE PROMPTS
# ==============================================================================
def app_torneo():
    engine = obtener_conexion()

    st.title('🏆 Torneo de Prompts')

    # ------------------------------------------------------------------
    # 1. ESTADO DE SESIÓN
    # ------------------------------------------------------------------
    defaults = {
        'autenticado': False,   # ¿la contraseña ya fue validada?
        'esperando': False,     # ¿dentro del sistema pero sin pregunta activa?
        'idalumno': None,       # integrante que está respondiendo
        'nombre': '',           # nombre del integrante
        'equipo': '',           # equipo del integrante
        'idpregunta': None,     # pregunta sorteada
        'pregunta': '',         # texto de la pregunta
        'hora_inicio': None,    # momento en que se activó la pregunta
        'candidato': None,      # integrante elegido al azar (aún sin validar)
    }
    for clave, valor in defaults.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor

    # ------------------------------------------------------------------
    # PANTALLA DE TIEMPO AGOTADO
    # ------------------------------------------------------------------
    if st.session_state['hora_inicio'] is not None:
        tiempo_limite = st.session_state['hora_inicio'] + timedelta(minutes=DURACION_MINUTOS)
        if ahora_mexico() >= tiempo_limite:
            st.error(
                '⏰ **¡Tiempo agotado!**\n\n'
                'Los 5 minutos han terminado. Cierra esta pestaña.'
            )
            # Limpieza total de la sesión
            for clave in defaults:
                st.session_state[clave] = defaults[clave]
            st.stop()

    # ------------------------------------------------------------------
    # 2. ACCESO: EQUIPO -> INTEGRANTE AL AZAR -> CONTRASEÑA
    # ------------------------------------------------------------------
    if not st.session_state['autenticado']:
        st.subheader('🔐 Acceso del Equipo')

        try:
            with engine.connect() as conn:
                df_equipos = pd.read_sql(
                    text(
                        'SELECT DISTINCT LTRIM(RTRIM(equipo)) AS equipo '
                        'FROM YahAlumno WHERE estatus = 1 ORDER BY equipo'
                    ),
                    conn,
                )
        except Exception as err:
            st.error(f'⚠️ Error al conectar con la base de datos: {err}')
            st.stop()

        # A. Selección del equipo
        equipo_sel = st.selectbox(
            '🧑‍🤝‍🧑 Selecciona tu Equipo:',
            options=df_equipos['equipo'].tolist(),
        )

        # B. Botón para elegir integrante al azar
        if st.button('🎲 Elegir integrante al azar', use_container_width=True):
            try:
                with engine.connect() as conn:
                    df_integrantes = pd.read_sql(
                        text(
                            'SELECT idalumno, nombre FROM YahAlumno '
                            'WHERE LTRIM(RTRIM(equipo)) = :eq AND estatus = 1'
                        ),
                        conn,
                        params={'eq': equipo_sel},
                    )
                elegido = df_integrantes.sample(1).iloc[0]  # 1 registro al azar
                st.session_state['candidato'] = {
                    'idalumno': int(elegido['idalumno']),
                    'nombre': elegido['nombre'],
                    'equipo': equipo_sel,
                }
            except Exception as err:
                st.error(f'⚠️ Error al elegir integrante: {err}')

        # C. Si ya hay candidato, pedir su contraseña
        if st.session_state['candidato']:
            cand = st.session_state['candidato']
            st.info(
                f"🎯 Integrante seleccionado: **{cand['nombre']}** "
                f"(Equipo: {cand['equipo']})"
            )

            with st.form('form_login_torneo'):
                pwd_input = st.text_input('🔑 Contraseña del integrante:', type='password')
                btn_validar = st.form_submit_button(
                    '🔓 Validar y comenzar', type='primary', use_container_width=True
                )

                if btn_validar:
                    if not pwd_input.strip():
                        st.warning('⚠️ Ingresa la contraseña.')
                    else:
                        try:
                            query_valida = text("""
                                SELECT idalumno, nombre, LTRIM(RTRIM(equipo)) AS equipo
                                FROM YahAlumno
                                WHERE idalumno = :ida
                                  AND LTRIM(RTRIM(password)) = :pwd
                                  AND estatus = 1
                            """)
                            with engine.connect() as conn:
                                res = conn.execute(
                                    query_valida,
                                    {'ida': cand['idalumno'], 'pwd': pwd_input.strip()},
                                ).fetchone()

                            if res:
                                # Contraseña correcta -> pasa a la sala de espera.
                                # NO se sortea pregunta aquí: se sortea cuando
                                # el administrador active una (estatus = 1).
                                st.session_state['autenticado'] = True
                                st.session_state['esperando'] = True
                                st.session_state['idalumno'] = res.idalumno
                                st.session_state['nombre'] = res.nombre
                                st.session_state['equipo'] = res.equipo
                                st.rerun()
                            else:
                                st.error('❌ Contraseña incorrecta. Vuelve a intentar.')
                        except Exception as err:
                            st.error(f'⚠️ Error al validar: {err}')

        st.stop()

    # ------------------------------------------------------------------
    # 2.5 SALA DE ESPERA (la pregunta aún no está activa)
    # ------------------------------------------------------------------
    if st.session_state['esperando']:
        st.success(f"✅ Contraseña validada. Bienvenido(a), **{st.session_state['nombre']}**.")
        st.warning(
            '⏳ **Aún no hay una pregunta activa.**\n\n'
            'Espera a que el administrador la active. Esta pantalla se '
            'actualiza sola; cuando la pregunta esté lista entrarás '
            'automáticamente a tu reto de 5 minutos.'
        )

        col_hora, col_salir = st.columns([3, 1])
        with col_hora:
            _, hora_actual = obtener_fecha_hora_mexico()
            st.caption(f'🔄 Última actualización: **{hora_actual}**')
        with col_salir:
            if st.button('🔒 Salir', use_container_width=True):
                for clave in defaults:
                    st.session_state[clave] = defaults[clave]
                st.rerun()

        # Búsqueda automática de pregunta activa.
        # El reloj arranca en la hora de activación guardada por el
        # administrador (hora_activacion): es la MISMA para todos los equipos.
        # Si la columna no existe o está vacía, se conserva el comportamiento
        # anterior (cada equipo arranca su reloj al entrar).
        try:
            with engine.connect() as conn:
                try:
                    preg = conn.execute(text(
                        'SELECT TOP 1 idpregunta, pregunta, hora_activacion '
                        'FROM YahPregunta WHERE estatus = 1 ORDER BY NEWID()'
                    )).fetchone()
                    tiene_hora = True
                except Exception:
                    conn.rollback()
                    preg = conn.execute(text(
                        'SELECT TOP 1 idpregunta, pregunta '
                        'FROM YahPregunta WHERE estatus = 1 ORDER BY NEWID()'
                    )).fetchone()
                    tiene_hora = False

            if preg:
                if tiene_hora and preg.hora_activacion is not None:
                    # Momento exacto en que el admin activó la ronda (servidor)
                    base = preg.hora_activacion.replace(
                        tzinfo=timezone(timedelta(hours=-6)))
                else:
                    base = ahora_mexico()  # compatibilidad: reloj por equipo
                st.session_state['idpregunta'] = preg.idpregunta
                st.session_state['pregunta'] = preg.pregunta
                st.session_state['esperando'] = False
                st.session_state['hora_inicio'] = base  # ¡ARRANCA EL TEMPORIZADOR!
                st.rerun()
        except Exception as err:
            st.error(f'⚠️ Error al buscar la pregunta: {err}')

        time.sleep(ESPERA_SEGUNDOS)
        st.rerun()

    # ------------------------------------------------------------------
    # 3. ZONA DE TRABAJO (temporizador + pregunta + campos de respuesta)
    # ------------------------------------------------------------------
    tiempo_limite = st.session_state['hora_inicio'] + timedelta(minutes=DURACION_MINUTOS)
    restante = tiempo_limite - ahora_mexico()
    total_seg = int(restante.total_seconds())
    mins, segs = divmod(total_seg, 60)

    # A. Barra de estado: temporizador + participante
    col_tiempo, col_persona = st.columns(2)
    with col_tiempo:
        st.metric('⏳ Tiempo restante', f'{mins:02d}:{segs:02d}')
        st.progress(min(1.0, total_seg / (DURACION_MINUTOS * 60)))
    with col_persona:
        st.metric('👤 Participante', st.session_state['nombre'])
        st.caption(f"🧑‍🤝‍🧑 Equipo: **{st.session_state['equipo']}**")

    if total_seg <= 60:
        st.warning('⚠️ ¡Último minuto! Termina de pegar tu resultado.')

    st.divider()

    # B. La pregunta sorteada
    st.subheader('❓ Pregunta del reto')
    st.warning(st.session_state['pregunta'])

    st.divider()

    # C. Campos para pegar el prompt y el resultado
    st.subheader('📝 Tu respuesta')
    st.text_area(
        'Prompt diseñado:',
        key='prompt_texto',
        height=180,
        placeholder='Pega aquí el prompt que creaste...',
    )
    st.text_area(
        'Resultado de la consulta:',
        key='resultado_texto',
        height=150,
        placeholder='Pega aquí el resultado que te devolvió la IA...',
    )

    # ------------------------------------------------------------------
    # D. BOTÓN GUARDAR: inserta en YahRespuestas y cierra la sesión
    # ------------------------------------------------------------------
    if st.button('💾 Guardar respuesta', type='primary', use_container_width=True):
        if not st.session_state['prompt_texto'].strip():
            st.warning('⚠️ Debes pegar el prompt que diseñaste.')
        elif not st.session_state['resultado_texto'].strip():
            st.warning('⚠️ Debes pegar el resultado de la consulta.')
        else:
            try:
                # Tiempo real empleado (desde que se activó la pregunta)
                tiempo_usado = ahora_mexico() - st.session_state['hora_inicio']
                segundos_usados = max(0, int(tiempo_usado.total_seconds()))
                minutos_usados, segundos_resto = divmod(segundos_usados, 60)

                query_insert = text("""
                    INSERT INTO YahRespuestas
                        (IdPregunta, equipo, idAlumno, Prompt, Resultado,
                         Minutos, Segundo, Valor, Bonus)
                    VALUES
                        (:idpregunta, :equipo, :idalumno, :prompt, :resultado,
                         :minutos, :segundo, :valor, :bonus)
                """)

                with engine.begin() as conn:
                    conn.execute(
                        query_insert,
                        {
                            'idpregunta': st.session_state['idpregunta'],
                            'equipo': int(st.session_state['equipo']),
                            'idalumno': str(st.session_state['idalumno']),
                            'prompt': st.session_state['prompt_texto'],
                            'resultado': st.session_state['resultado_texto'],
                            'minutos': minutos_usados,
                            'segundo': segundos_resto,
                            'valor': None,   # se califica después (NULL por ahora)
                            'bonus': None,   # se califica después (NULL por ahora)
                        },
                    )

                # Pantalla de confirmación y cierre limpio de sesión
                st.success(
                    '✅ **¡Respuesta guardada con éxito!**\n\n'
                    f"⏱️ Tiempo empleado: **{minutos_usados} min {segundos_resto} seg**\n\n"
                    '🔒 La sesión ya se cerró por seguridad.'
                )
                st.info('Esta pestaña se cerrará automáticamente. '
                        'Si no se cierra, puedes hacerlo manualmente con **Ctrl + W**.')

                # Intento de cierre automático de la pestaña (los navegadores
                # solo lo permiten en pestañas abiertas por script; si lo
                # bloquean, el usuario la cierra manualmente).
                components.html(
                    """
                    <script>
                        setTimeout(function() {
                            window.close();
                        }, 2500);
                    </script>
                    """,
                    height=0,
                )

                # Limpieza total de la sesión
                for clave in defaults:
                    st.session_state[clave] = defaults[clave]
                if 'prompt_texto' in st.session_state:
                    del st.session_state['prompt_texto']
                if 'resultado_texto' in st.session_state:
                    del st.session_state['resultado_texto']
                st.stop()

            except Exception as err:
                st.error(f'⚠️ Error al guardar la respuesta: {err}')

    # E. Refresco automático para que el temporizador corra segundo a segundo
    time.sleep(1)
    st.rerun()


# ==============================================================================
# EJECUCIÓN DIRECTA
# ==============================================================================
if __name__ == '__main__':
    app_torneo()