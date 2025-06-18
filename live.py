import http.server
import requests
import socketserver
import os
import random
import urllib
import wave
import io
import threading
import copy
import traceback
import time
import subprocess
import collections
from mutagen.mp3 import MP3

path = "localhost"
port = 80
base_dir = os.path.dirname(__file__)
dirs = next(os.walk(base_dir))[1]
conn_pool = None
stations = {}
threads = []
print_lock = threading.Lock()
CHUNK_SIZE = 8192
PREBUFFER_SIZE = 10
run_signal = True

class Station():
    def __init__(self, name):
        self.station_name = name
        self.song_name = ""
        self.song_path = ""
        self.audio_buffer = io.BytesIO()
        self.prebuffer = collections.deque([], PREBUFFER_SIZE)
        self.prebuffer_lock = threading.Lock()
        self.song_pos = 0


class Connection():
    def __init__(self):
        self.buffer = io.BytesIO()


class ConnectionPool():
    def __init__(self):
        self.conn_pool_lock = threading.Lock()
        self.connections = {}
        for d in dirs:
            self.connections[d] = []

    def addConnection(self, station, conn):
        self.connections[station].append(conn)

    def deleteConnection(self, station, conn):
        self.connections[station].remove(conn)

    def broadcastToConnections(self, station_name):
        for cn in self.connections[station_name]:
            cn.buffer = copy.deepcopy(stations[station_name].audio_buffer)


class StationServer():
    def __init__(self, station_name):
        self.station = station_name
        self.file = None
        self.delay = 150
        self.switchSong()

    def switchSong(self):
        path = os.path.join(base_dir, self.station)
        new_song = random.choice(os.listdir(path))
        with print_lock:
            print("Station {} is now playing {}".format(self.station, new_song))
        stations[self.station].song_name = new_song
        stations[self.station].song_path = os.path.join(base_dir, self.station, new_song)
        if self.file:
            self.file.close()
        self.file = open(stations[self.station].song_path, 'rb')
        source = MP3(stations[self.station].song_path)
        length = source.info.length
        self.delay = (length * CHUNK_SIZE) / os.path.getsize(stations[self.station].song_path)
        print(self.delay)


    #run this every 150 ms
    def stream(self):
        while run_signal:
            start_time = time.time()
            data = None
            try:
                data = self.file.read(CHUNK_SIZE)
                with stations[self.station].prebuffer_lock:
                    stations[self.station].prebuffer.append(copy.deepcopy(stations[self.station].audio_buffer))
                stations[self.station].audio_buffer = io.BytesIO()
                written = stations[self.station].audio_buffer.write(bytes(data))
                stations[self.station].audio_buffer.seek(0)
                curr_pos = self.file.tell()
                line = self.file.readline()
                self.file.seek(curr_pos)
                if not line:
                    self.switchSong()
                conn_pool.broadcastToConnections(self.station)
            except:
                pass
                #print(traceback.format_exc())
                

            end_time = time.time()
            delta = end_time - start_time
            with print_lock:
                print(delta)
            time.sleep(max(self.delay - delta, 0))
        threads.remove(threading.current_thread())


class ReqHandler(http.server.SimpleHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        #self.send_header('Content-Type', 'audio/x-wav')
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header("Connection", "keep-alive")
        #self.send_header('Transfer-Encoding', 'chunked')
        #self.send_header('Content-Disposition', "attachment;filename*=UTF-8''{}".format(urllib.parse.quote(self.filename.encode('utf-8'))))
        self.end_headers()

    def resolvePath(self):
        if self.path == "/":
            return None
        elif self.path == "/favicon.ico":
            #self.path = os.path.join("live", "favicon.ico")
            #return True
            return None
        else:
            self.station = self.path.strip("/").strip("..").replace("\\\\", "\\")
            self.path = stations[self.station].song_path
            return True

    def continuousPlayback(self, connection):
        conn_alive = True
        with stations[self.station].prebuffer_lock:
            for i in stations[self.station].prebuffer:
                self.wfile.write(i.getvalue())
        while conn_alive:
            try:
                self.wfile.write(bytes(connection.buffer.getvalue()))
                connection.buffer = io.BytesIO()
            except:
                with conn_pool.conn_pool_lock:
                    conn_pool.deleteConnection(self.station, connection)
                conn_alive = False
                break
            time.sleep(0.5)
        threads.remove(threading.current_thread())

    def writeContent(self):
        if self.path.endswith(".mp3"):
            conn = Connection()
            conn_pool.addConnection(self.station, conn)
            new_thread = threading.Thread(target=self.continuousPlayback, args=(conn, ))
            new_thread.start()
            threads.append(new_thread)
        else:
            return None
            with open(self.path, mode='rb') as f:
                content = f.read()
                self.wfile.write(content)

    def do_GET(self):
        if self.resolvePath() is None:
            return
        if len(stations[self.station].prebuffer) != PREBUFFER_SIZE:
            pass
            #return
        self._set_headers()
        self.writeContent()

def serve(handle):
    try:
        with http.server.ThreadingHTTPServer(("localhost", port), handler) as httpd:
            httpd.serve_forever()
    except:
        return


if __name__ == "__main__":
    conn_pool = ConnectionPool()
    handler = ReqHandler
    for st in dirs:
        stations[st] = Station(st)

    for e in stations:
        st = StationServer(e)
        st_thread = threading.Thread(target=st.stream)
        st_thread.daemon = True
        st_thread.start()
        threads.append(st_thread)

    serve(handler)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Trying to stop!")
        run_signal = False
        st_thread.join()
        for i in threads:
            i.join()