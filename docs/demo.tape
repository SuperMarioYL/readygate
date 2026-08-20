Output assets/demo.gif
RequireEnvironment local
Set FontSize 14
Set Width 1200
Set Height 560
Set Padding 20
Set Theme "{ "background": "#1D1D1F" }"

# Start the mock CN-model endpoint in the background (stdlib only).
Type "python3 examples/mock_endpoint.py &"
Enter
Sleep 1s

# Run ReadyGate: NO (malformed JSON) -> repaired -> re-verified: YES
Type "readygate probe http://localhost:8000/v1"
Enter
Sleep 3s

# Show the machine-readable certificate
Type "cat readygate-cert.json"
Enter
Sleep 1s

# Stop the mock endpoint
Type "kill %1"
Enter
Sleep 500ms
