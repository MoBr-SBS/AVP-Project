## Installation des I²C-Servers auf dem Raspberry Pi

Diese Anleitung setzt voraus, dass du dich per **SSH** mit deinem Raspberry Pi verbunden hast und die PyCharm **virtuelle Umgebung** (**`PythonProject`**) existiert.

### A. System-Vorbereitung (Einmalig)

Diese Befehle installieren systemweite Programme und aktivieren die I²C-Schnittstelle.

#### 1\. I²C-Schnittstelle aktivieren

Das Betriebssystem muss I²C freigeben.

```bash
sudo raspi-config # Starte das Konfigurationstool
```

  * Navigiere zu **3 Interface Options** → **I5 I2C** → **Yes** (Ja).
  * Beende das Tool und starte den Pi neu.

#### 2\. Wichtige System-Tools installieren

Installiere den I²C-Test, Systemwerkzeuge (`build-essential`) und den Compiler **`swig`**, der für die Python-Bindungen erforderlich ist.

```bash
sudo apt update
sudo apt install i2c-tools swig build-essential
```

#### 3\. Spezielle C-Bibliothek (`liblgpio`) kompilieren

Die `adafruit-blinka`-Bibliothek benötigt eine spezielle C-Schnittstelle, die manuell installiert werden muss.

```bash
# Herunterladen und entpacken
wget http://abyz.me.uk/lg/lg.zip
unzip lg.zip
cd lg

# Kompilieren und systemweit installieren
make
sudo make install

# Aufräumen (optional)
cd ..
rm -r lg lg.zip
```

-----

### B. Python-Abhängigkeiten installieren

Die Python-Pakete müssen in die virtuelle Umgebung installiert werden, die PyCharm nutzt.

#### 1\. Virtuelle Umgebung aktivieren

Dies stellt sicher, dass alle folgenden `pip`-Befehle im richtigen Ordner landen.

```bash
source /home/moritz/.virtualenvs/PythonProject/bin/activate
```

#### 2\. Python-Pakete installieren

Installiere alle benötigten Pakete. *Alle diese Pakete können alternativ auch über die **PyCharm-Oberfläche** (Settings -\> Python Interpreter) installiert werden.*

```bash
pip install websockets adafruit-circuitpython-pca9685 adafruit-circuitpython-motor
pip install lgpio setuptools
```

-----

### C. Funktionstest

#### 1\. Hardware überprüfen

Verbinde das PCA9685-Board mit dem Raspberry Pi.

```bash
i2cdetect -y 1
```

*(Die I²C-Adresse, meist **`40`**, sollte in der Tabelle erscheinen.)*

#### 2\. Server vorbereiten und ausführen

  * Stelle in deinem Python-Code sicher, dass der Server auf **`'0.0.0.0'`** lauscht, damit andere Geräte im Netzwerk darauf zugreifen können.
  * Führe den Server über dein **PyCharm Remote Development** aus.

#### 3\. Client verbinden

Verbinde deinen Client (Testskript oder Swift-App) mit der **lokalen IP-Adresse** deines Raspberry Pi (z.B. `ws://192.168.1.150:8765`).

Wenn die Verbindung hergestellt wird und die Servos auf gesendete Werte reagieren, ist die gesamte Kette erfolgreich eingerichtet\!
