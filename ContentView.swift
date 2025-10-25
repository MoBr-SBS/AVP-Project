import SwiftUI

struct ContentView: View {
    
    // MARK: - UI Zustand (Textfelder & Slider-Werte)
    @State private var ip_adress = "192.168.10.43" // Standardwert für einfache Tests
    @State private var port = "8765"
    
    @State private var panValue: Double = 90.0 // Mittenposition Pan
    @State private var tiltValue: Double = 0.0  // Mittenposition Tilt
    
    // MARK: - Der Logik-Motor (MUSS HIER GESTARTET WERDEN!)
    // @StateObject stellt sicher, dass die Verbindung aktiv bleibt.
    @StateObject var wsController = WebsocketController()
    
    var body: some View {
        VStack(spacing: 15) {
            
            // MARK: - VERBINDUNGSSTATUS (Gelesen aus dem Controller)
            Text(wsController.connectionStatusText)
                .font(.headline)
                .foregroundColor(wsController.isConnected ? .green : .red)
                .padding(.bottom, 10)
            
            // MARK: - EINGABEFELDER
            
            Text("**Raspberry Pi - IP Adresse**")
            TextField("z.B. 192.168.1.1", text: $ip_adress)
                .textFieldStyle(.roundedBorder)
            
            Text("**Websocket-Port**")
            TextField("Standard: 8765", text: $port)
                .textFieldStyle(.roundedBorder)
            
            // MARK: - CONNECT / TRENNEN BUTTON
            
            Button(wsController.isConnected ? "Trennen" : "Connect") {
                if wsController.isConnected {
                    // Wenn verbunden, trenne die Verbindung
                    wsController.disconnect()
                } else {
                    // Wenn nicht verbunden, starte den Verbindungsaufbau
                    wsController.connect(ipAddress: ip_adress, port: port)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(wsController.isConnected ? .red : .green) // Rote Farbe beim Trennen
            .padding(.vertical)

            Divider()
            
            // Die Slider und der Sende-Button werden ausgegraut, wenn keine Verbindung besteht.
            Group {
                
                // MARK: - PAN SLIDER
                
                Text("\n**Pan** (Aktuell: \(panValue, specifier: "%.0f")°)")
                Slider(value: $panValue, in: 0...180, step: 1)
                
                // MARK: - TILT SLIDER
                
                Text("\n**Tilt** (Aktuell: \(tiltValue, specifier: "%.0f")°)")
                Slider(value: $tiltValue, in: -90...90, step: 1)
                
                // MARK: - SEND BUTTON
                
                Button("Sendebefehl auslösen") {
                    // Sende die aktuellen Werte von Pan und Tilt
                    wsController.sendPanTilt(pan: panValue, tilt: tiltValue)
                }
                .buttonStyle(.borderedProminent)
            }
            // Logik zum Deaktivieren/Ausgrauen der Bedienelemente, wenn nicht verbunden
            .opacity(wsController.isConnected ? 1 : 0.5)
            .disabled(!wsController.isConnected)
            
            Spacer()
        }
        .padding(40)
    }
}

#Preview {
    ContentView()
}
