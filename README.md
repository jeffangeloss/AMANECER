# AMANECER++

AMANECER++ descarga con un solo comando el material de todos los cursos de Blackboard de la
Universidad de Lima, con sus carpetas y subcarpetas, y las grabaciones de Zoom de cada curso. Cada
corrida trae solo lo nuevo, porque salta lo que ya está en el disco con el mismo tamaño, así que se
puede repetir cada semana.

Cada persona entra con su propia cuenta. La sesión se guarda solo en su computadora y ningún dato
sale de ella salvo hacia Blackboard y Zoom.

## Requisitos

1. Python 3.10 o superior. En Windows se instala desde https://www.python.org/downloads/ con la
   casilla «Add python.exe to PATH» marcada.
2. Google Chrome, porque el inicio de sesión se hace en una ventana de Chrome.
3. Una cuenta de la ULima con acceso a Blackboard y su MFA a la mano.
4. Espacio en disco. Las grabaciones de un curso ocupan entre 5 GB y 12 GB por semestre.

## Instalación

Primero se descarga el repositorio, con `git clone` o con el botón «Code» y «Download ZIP» de
GitHub, y se abre una terminal en esa carpeta.

En Windows, desde PowerShell, se corre este comando.

```powershell
powershell -ExecutionPolicy Bypass -File .\instalar.ps1
```

En macOS o Linux, desde la Terminal, se corre este otro.

```bash
./instalar.sh
```

El instalador agrega las librerías de `requirements.txt` y avisa si falta Python o Chrome.

## Uso

En Windows el comando es este.

```powershell
powershell -ExecutionPolicy Bypass -File .\bb-todo.ps1
```

En macOS o Linux es este otro.

```bash
./bb-todo.sh
```

La primera vez se abre Chrome con la página de Blackboard. Ahí se inicia sesión con el usuario, la
clave y el MFA, y la ventana se cierra sola cuando cargan los cursos. Desde ese momento el comando
sigue solo y recorre cuatro pasos, que son renovar la sesión, bajar los materiales, bajar las
grabaciones y mostrar un resumen de lo que hay en el disco frente a lo que hay en Blackboard. La
sesión dura semanas, y cuando vence el comando vuelve a abrir Chrome para iniciarla otra vez.

El primer ciclo completo puede tardar varias horas por el peso de las grabaciones. Si se corta, basta
con volver a correr el comando, porque salta lo terminado y sigue con lo que faltó.

### Opciones

Las opciones se agregan al final del comando, por ejemplo `.\bb-todo.ps1 --curso DEVOPS`.

| Opción | Qué hace |
| --- | --- |
| `--curso TEXTO` | Procesa solo los cursos cuyo nombre contiene ese texto |
| `--sin-grabaciones` | Baja solo los materiales |
| `--sin-materiales` | Baja solo las grabaciones |
| `--destino RUTA` | Guarda todo en otra carpeta |
| `--max-mb N` | Omite los documentos de más de N MB |
| `--login` | Abre Chrome para iniciar sesión aunque la sesión siga vigente |

## Dónde quedan los archivos

### Banco Integral compartido

El destino por defecto es el Banco Integral compartido en Google Drive, dentro de la carpeta del
semestre que indica Blackboard, por ejemplo `[2026-2] NOCHE NÁUFRAGA`. Cada curso queda así.

```text
[E.P.L.A.] Banco Integral CIS,CII & DEMÁS/
  [2026-2] NOCHE NÁUFRAGA/
    [2026-2] DEVOPS/
      [Archivos - 1051] NOMBRE DEL PROFESOR/      (misma estructura de Blackboard)
      [Grabaciones - 1051] NOMBRE DEL PROFESOR/   S1.Clase 1 - 27.08.26.mp4 ...
```

La sección y el profesor separan las carpetas, de modo que dos personas en secciones distintas no
mezclan su material y dos personas en la misma sección comparten una sola copia. El nombre completo
del curso sale de `nombres_cursos.json`, y un curso que no figura ahí usa la abreviatura de
Blackboard. Para agregar un curso basta con sumar una línea a ese archivo.

Para usar el Banco hacen falta tres condiciones.

1. Google Drive para escritorio instalado y con sesión iniciada en la cuenta que tiene acceso al
   Banco.
2. Un acceso directo del Banco en «Mi unidad». En drive.google.com, en «Compartido conmigo», se
   hace clic derecho sobre `[E.P.L.A.] Banco Integral CIS,CII & DEMÁS` y se elige «Organizar» y
   «Agregar acceso directo», con «Mi unidad» como destino.
3. Permiso de editor sobre la carpeta del semestre. Con permiso de lector la carpeta se ve, pero no
   admite archivos nuevos.

El comando prueba al inicio si puede escribir en el Banco. Si no lo encuentra o no tiene permiso, lo
avisa y guarda todo en la carpeta personal, sin detenerse. Si la carpeta del Banco tiene otra
ubicación, se agrega una línea `BB_BANCO=RUTA` al archivo `.env` con la ruta completa de
`[E.P.L.A.] Banco Integral CIS,CII & DEMÁS`.

### Carpeta personal

Los cursos sin semestre, como los de inducción o los exámenes de inglés, y todo lo que no puede ir
al Banco, van a una carpeta llamada `Blackboard ULIMA`. En Windows se crea en el disco con más
espacio libre que no sea C:, o en la carpeta del usuario si no hay otro disco. En macOS va a «Mi
unidad» de Google Drive para escritorio si está instalado, y si no, a la carpeta del usuario. Ahí
cada curso tiene su carpeta con la estructura de Blackboard y sus grabaciones en `Grabaciones`.

Las grabaciones se nombran como `S3.Clase 7 - 09.09.26.mp4`, donde S3 es la semana del curso y 7 el
número de la clase. Para fijar la carpeta personal se agrega una línea `BB_DESTINO=RUTA` al archivo
`.env` que crea el primer inicio de sesión, y la opción `--destino RUTA` manda todo a esa ruta,
Banco incluido.

## Seguridad

El archivo `.env` y la carpeta `.perfil-chrome` guardan la sesión de Blackboard de quien los creó.
Con ellos cualquier persona entra a esa cuenta, así que no se comparten, no se suben a ningún lado y
no se copian a otra computadora. El `.gitignore` del repositorio ya los excluye.

## Uso responsable

El material y las grabaciones son de los docentes y de la Universidad. Cada estudiante baja lo de
sus propios cursos para estudiar, y no los redistribuye ni los publica. El comando deja una pausa
entre pedidos para no sobrecargar Blackboard, y esa pausa no se quita.

## Problemas frecuentes

| Mensaje | Qué hacer |
| --- | --- |
| «No se completo el login a tiempo» | Volver a correr el comando e iniciar sesión dentro de los 5 minutos |
| «La sesion SSO ya no sirve» | Correr el comando con `--login` |
| «Ningun curso respondio sin ventana» | Ninguna acción. El comando reintenta solo con Chrome visible |
| «FALLA» en algún archivo | Volver a correr el comando, que reintenta lo que faltó |
| PowerShell dice que no puede ejecutar scripts | Usar el comando con `-ExecutionPolicy Bypass` de arriba |

Cada corrida deja su registro completo en la carpeta `logs`, sin los datos de la sesión.
