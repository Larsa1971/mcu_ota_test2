# uping.py — förenklad ping som returnerar True/False
import gc
import socket
import struct
import utime

def checksum(data):
    if len(data) & 1:
        data += b'\0'
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xffff)
    s = s + (s >> 16)
    return ~s & 0xffff

def ping(host, timeout=2000, size=32):
    """Returnerar True om ping lyckas, annars False."""
    try:
        addr = socket.getaddrinfo(host, 1)[0][-1][0]
    except:
        return False

    packet_id = utime.ticks_cpu() & 0xFFFF
    seq = 1

    # Bygg ICMP echo request
    header = struct.pack('!BBHHH', 8, 0, 0, packet_id, seq)
    data = b'Q' * size
    chk = checksum(header + data)
    packet = struct.pack('!BBHHH', 8, 0, chk, packet_id, seq) + data

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, 1)
        sock.settimeout(timeout / 1000)
        sock.sendto(packet, (addr, 1))
        sock.recv(1024)
        sock.close()
        gc.collect()
        return True
    except:
        gc.collect()
        return False

