import socket
import json

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect(("3.219.70.73", 5000))

    quit = False
    while not quit:
        text = input(" > (add, quit) ")
        
        if text == "quit":
            quit = True
            break
        # quit = text == "quit"

        request = {}
        if text == "add":
            request = {
                "type": "add",
                "a": float(input("a: ")),
                "b": float(input("b: ")),
            }
        if text == "greet":
            request = {
                "type": "greet",
                "name": input("name: "),
            }

        msg = json.dumps(request).encode("utf-8")
        s.sendall(msg)
        s.settimeout(5.0)
        try:
            reply = s.recv(4096)
            reply_json = json.loads(reply.decode("utf-8"))

            if reply_json.get("ok"):
                print(reply_json["result"])
            else:
                print(reply_json["error"])

        except TimeoutError:
            print("The server did not respond in 5 seconds")
        #print("The server said:", reply.decode("utf-8"))   
