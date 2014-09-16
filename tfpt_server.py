from socket import *
import sys
import select
import pprint
import os
import threading
import random

class Download:
    'Maintain connection state'

    def __init__(self, request, addr):
        self.filename = request['filename']
        self.address = addr
        self.sequence = 1
        self.tid = random.randint(1024,65535)

    def createPackage(self, string):
        pkg = chr(0) + chr(3) + chr(0) + chr(self.sequence) + string
        return pkg
 

###################################################
# Define a handler for threading
# Will serve each connection and then close socket
###################################################

def connectionThread(connection):

    # print log info file "example_data1" requested from 127.0.0.1:37242
    print 'file "' + connection.filename + '" requested from ' + str(connection.address[0]) + ':' + str(connection.address[1])

    # create and bind to a socket for this file session
    connSocket = socket(AF_INET, SOCK_DGRAM)
    connSocket.bind(('', connection.tid))

    # TODO: error handling
    target = open(connection.filename)

    data = target.read(512)

    # TODO: check somehow if last package was exactly 512 bytes, then we must send a 0 length package
    while len(data) > 0:
        pkg = connection.createPackage(data)
        connSocket.sendto(pkg, connection.address)

        # wait for ack
        response, clientAddress = connSocket.recvfrom(520)

        # TODO: check the ACK
        # Just increase sequence number for now
        connection.sequence = connection.sequence + 1;

        # read next chunk
        data = target.read(512)

    # All work done for thread, close socket
    connSocket.close()


###############################################
# Helper functions
###############################################

def parseRequest(rqString):

    request = { 'opcode': 0, 'filename': '', 'mode': '' }

    # opcode stored in first 2 bytes, only need to read second since it is 1-5
    opcode = ord(rqString[1])
    request['opcode'] = opcode

    if opcode != 1 and opcode != 2:
        return request

    strings = rqString[2:].split('\0')
    request['filename'] = strings[0]
    request['mode'] = strings[1]

    return request

def createErrorPackage(errorCode, errorMsg):
    tempSocket = socket(AF_INET, SOCK_DGRAM)

    if errorCode < 0 or errorCode > 7:
        raise Exception('ErrorCode out of bounds')

    package = chr(0) + chr(5) + chr(errorCode) + chr(0) + errorMsg + chr(0)

    return package

###############################################
# Start of main program
###############################################

if (len(sys.argv) != 3):
    print 'Needs two arguments, port number and folder name'
    sys.exit(1)

# read and validate port
port = int(sys.argv[1])
if port < 1024 or port > 65536:
    raise Exception('Invalid port number given')

# also validate folder name
folder = sys.argv[2]
try:
    os.chdir(folder)
except Exception, e:
    raise Exception('Could not change to given folder')

listenSocket = socket(AF_INET, SOCK_DGRAM)
listenSocket.bind(('', port))
print 'Server ready. Using port: ' + str(port)

while 1:
    message, clientAddress = listenSocket.recvfrom(2048) 
    print 'connection from: ' + str(clientAddress[0]) + ':' + str(clientAddress[1])

    rq = parseRequest(message)

    print rq['opcode'];
    print rq['filename'];
    print rq['mode'];

    # Disallow all write requests
    if rq['opcode'] == 2:
        pkg = createErrorPackage(2, 'Write not allowed')
        listenSocket.sendto(pkg, clientAddress)
        continue

    # Handle read requests
    if rq['opcode'] == 1:

        # First check if filename contains a path. That is forbidden
        if rq['filename'] != os.path.basename(rq['filename']):
            print rq['filename']
            print os.path.basename(rq['filename'])
            pkg = createErrorPackage(2, 'No path parts allowed')
            listenSocket.sendto(pkg, clientAddress)
            continue

        # Now see if we can read the file
        if not os.path.isfile(rq['filename']):
            pkg = createErrorPackage(1, 'File not found')
            listenSocket.sendto(pkg, clientAddress)
            continue            

        # And check for possible access to file permission
        if os.access(rq['filename'], os.R_OK) == False:
            pkg = createErrorPackage(2, 'Not allowed')
            listenSocket.sendto(pkg, clientAddress)
            continue

        # All checks passed. Deliver file
        conn = Download(rq, clientAddress)

        # dispatch to thread, set it as deamon as not to keep process alive
        thr = threading.Thread(target=connectionThread, args=(conn,))
        thr.deamon = True
        thr.start()

    # while True:
    #     readList, writeList, errorList = select.select([connectionSocket], [], [], 60)

    #     if (len(readList) == 0):
    #         peer = connectionSocket.getpeername()
    #         print 'connection closed after timeout: ' + str(peer[0]) + ':' + str(peer[1])
    #         break

    #     message = connectionSocket.recv(1024)

    #     if (len(message) == 0):
    #         peer = connectionSocket.getpeername()
    #         print 'connection closed by client: ' + str(peer[0]) + ':' + str(peer[1])
    #         break

    #     connectionSocket.send(message)

    #connectionSocket.close()

listenSocket.shutdown(2)
listenSocket.close()
