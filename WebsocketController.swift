import Foundation
import Combine

@MainActor
class WebsocketController: ObservableObject {
    
    @Published var isConnected: Bool = false
    @Published var connectionStatusText: String = "Nicht verbunden"
    
    private var webSocketTask: URLSessionWebSocketTask?
    
    // MARK: - VERBINDUNG HERSTELLEN
    
    func connect(ipAddress: String, port: String) {
        
        // 1. URL mit ws:// Protokoll erstellen
        guard !ipAddress.isEmpty, let url = URL(string: "ws://\(ipAddress):\(port)") else {
            self.connectionStatusText = "Fehler: Ungültige IP oder Port."
            return
        }
        
        // 2. Bestehende Verbindung trennen, falls vorhanden
        disconnect()

        // 3. Neue Session und Task erstellen
        let session = URLSession(configuration: .default)
        self.webSocketTask = session.webSocketTask(with: url)
        
        self.webSocketTask?.resume()
        self.connectionStatusText = "Verbinde zu \(ipAddress):\(port)..."
        
        // 4. Startet das Warten auf die erste Nachricht (Verbindungsbestätigung)
        self.receive()
    }
    
    // MARK: - LOGIK ZUM SENDEN
    
    func sendPanTilt(pan: Double, tilt: Double) {
        // ... (Der Code zum Senden ist unverändert und korrekt)
        guard self.isConnected, let task = webSocketTask else { return }
        
        let panValueRounded = pan.rounded()
        let tiltValueRounded = tilt.rounded()
        
        let messageString = "\(String(format: "%.0f", panValueRounded)),\(String(format: "%.0f", tiltValueRounded))"
        let message = URLSessionWebSocketTask.Message.string(messageString)
        
        task.send(message) { error in
            if let error = error {
                print("Fehler beim Senden: \(error)")
            } else {
                print("Gesendet: \(messageString)")
            }
        }
    }
    
    // MARK: - LOGIK ZUM EMPFANGEN & STATUS PRÜFEN
    
    private func receive() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            // Führt alle Statusänderungen auf dem Haupt-Thread aus (dank @MainActor)
            switch result {
            case .failure(let error):
                // Bei einem Fehler sofort trennen
                print("WebSocket-Empfangsfehler: \(error.localizedDescription)")
                self.isConnected = false
                self.connectionStatusText = "Verbindung fehlgeschlagen. Fehlercode: \(error._code)"
                
            case .success(let message):
                // Beim ersten Erfolg Status setzen
                if !self.isConnected {
                    self.isConnected = true
                    self.connectionStatusText = "Verbunden: Bereit zum Senden."
                    print("WebSocket: Verbindung erfolgreich bestätigt.")
                }
                
                // Wir können hier prüfen, ob die Nachricht "CONNECTION_SUCCESS" war
                switch message {
                case .string(let text):
                    print("Empfangen (Server): \(text)")
                case .data(let data):
                    print("Empfangen (Server): \(data.count) Bytes")
                @unknown default:
                    break
                }
                
                // Weiter auf Nachrichten lauschen (wichtig für Echtzeit)
                self.receive()
            @unknown default:
                break
            }
        }
    }
    
    // MARK: - VERBINDUNG TRENNEN
    
    func disconnect() {
        // Schließt die Verbindung mit Code 1001 (Going Away)
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        connectionStatusText = "Nicht verbunden."
    }
}
