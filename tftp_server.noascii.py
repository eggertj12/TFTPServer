from socket import *
import sys
import select
import pprint
import os
import threading
import random
import struct

class Download:
    'Maintain connection state'

    def __init__(self, request, addr):
        self.filename = request['filename']
        self.address = addr
        self.sequence = 1
        self.mode = request['mode']
        self.tid = random.randint(1024,65535)
        # remote TID is just the udp port number used
        self.remoteTid = addr[1]

    def createPackage(self, string):
        # Download data package has 2 bytes opcode (3) and 2 byte sequence number followed by the actual data
        # ! stands for network byte order, H is unsigned short
        pkg = struct.pack('! H H', 3, self.sequence) + string
        return pkg
 
###################################################
# Helper for reading a response on a connection
# Will try 5 times to resend package on timeout
#  - 5 is just an arbitrary value, did not find info in RFC
###################################################
def readResponse(connection, socket, pkg):

    retries = 0

    # select blocks on list of sockets until reading / writing is available
    # or until timeout happens
    readList, writeList, errorList = select.select([socket], [], [], 3)

    # empty list of sockets means a timeout occured
    # retry 5 times and then terminate connection if not successful
    while (len(readList) == 0 and retries < 5):
        # resend package and increment retries count
        socket.sendto(pkg, connection.address)
        retries += 1

        # wait for ack package
        readList, writeList, errorList = select.select([socket], [], [], 3)

    # the client has disappeared, just print an error message and break out of the loop
    if (retries >= 5):
        print 'Client seems to have disappeared. Terminating transfer'
        return (False, False)

    # read the available response
    return socket.recvfrom(520)

###################################################
# Helper for handling the response
###################################################
def handleResponse(connection, socket, pkg):

    # Loop until a valid package or timeout breaks out of the loop
    while True:
        response, clientAddress = readResponse(connection, socket, pkg)

        if (response == False):
            # reading has timed out cancel transfer
            return False

        # check if the incoming package is using the correct tid
        if (clientAddress[1] != connection.remoteTid):

            # Create an error package and send it to this misguided host, then just try to listen for more
            pkg = struct.pack('! H H', 5, 5) + 'Invalid tid' + chr(0)
            connSocket.sendto(pkg, clientAddress)
            continue

        # got this far, demux the response
        opcode, sequence = struct.unpack('! H H', response)

        if (opcode != 4):
            # A bogus package, only expecting ACK. Just ignore it
            continue

        if (sequence != connection.sequence):
            # Duplicate package toss it and listen again
            continue

        # have a valid package, increment counter wrapping around for huge files
        # this wrapping is not a standard method so it depends on client if it works
        # maybe should error out on this condition
        connection.sequence = connection.sequence + 1
        if connection.sequence >= 65536:
            connection.sequence = 1

        # All checks passed, return
        return True


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

    try:
        target = open(connection.filename)
    except Exception, e:
        # Hard fail on error. Have already checked file is available
        print 'File open error'
        print e
        sys.exit(1)

    # read first chunk
    data = target.read(512)
    # Need to handle special case of filesize % 512 = 0, set here in case file is 0 length
    lastLength = len(data)

    result = True
    while len(data) > 0:
        lastLength = len(data)
        retries = 0

        pkg = connection.createPackage(data)
        connSocket.sendto(pkg, connection.address)

        result = handleResponse(connection, connSocket, pkg)

        if (result == False):
            # something went wrong, break to abort transfer
            print 'Something wrong, timeout probably'
            break

        # read next chunk
        data = target.read(512)

    # handle case of mod 512 = 0 filesize
    if (lastLength == 512 and result == True):
        # correct response is just an empty package
        pkg = connection.createPackage('')
        connSocket.sendto(pkg, connection.address)

        # Wait for the response, retransmitting if needed
        handleResponse(connection, connSocket, pkg)


    # All work done for thread, close socket and file
    target.close()
    connSocket.close()


###############################################
# Helper functions
###############################################

def parseRequest(rqString):

    request = { 'opcode': 0, 'filename': '', 'mode': '' }

    # opcode stored in first 2 bytes, unpack alway returns a tuple
    data = struct.unpack_from('!H', rqString)
    request['opcode'] = data[0]

    # request are only 1 or 2, for RRQ and WRQ respectively
    if request['opcode'] != 1 and request['opcode'] != 2:
        return request

    # filename and mode are then stored in 0 terminated strings
    strings = rqString[2:].split('\0')

    if len(strings) < 2:
        raise Exception('Invalid request parameters')

    request['filename'] = strings[0]
    request['mode'] = strings[1].lower()

    # Only support netascii or octet mode (don't really understand the difference)
    if (request['mode'] != 'netascii') and (request['mode'] != 'octet'):
        raise Exception('Unsupported mode')

    return request

def createErrorPackage(errorCode, errorMsg):
    tempSocket = socket(AF_INET, SOCK_DGRAM)

    if errorCode < 0 or errorCode > 7:
        raise Exception('ErrorCode out of bounds')

    # package = chr(0) + chr(5) + chr(errorCode) + chr(0) + errorMsg + chr(0)
    pkg = struct.pack('! H H', 5, errorCode) + errorMsg + chr(0)

    return pkg

###############################################
# Start of main program
###############################################

if (len(sys.argv) != 3):
    print 'Needs two arguments, port number and folder name'
    sys.exit(1)

# read and validate port
port = int(sys.argv[1])
if port < 1024 or port > 65536:
    print 'Invalid port number given'
    sys.exit(1)

# also validate folder name
folder = sys.argv[2]
try:
    os.chdir(folder)
except Exception, e:
    print 'Could not change to given folder'
    sys.exit(1)

listenSocket = socket(AF_INET, SOCK_DGRAM)
listenSocket.bind(('', port))
print 'Server ready. Using port: ' + str(port)

while 1:
    message, clientAddress = listenSocket.recvfrom(2048) 
    # print 'connection from: ' + str(clientAddress[0]) + ':' + str(clientAddress[1])

    try:
        rq = parseRequest(message)
    except Exception, e:
        # Echo the exception message to stdout and silently drop malformed requests
        print e
        continue

    # Disallow all write requests
    if rq['opcode'] == 2:
        pkg = createErrorPackage(2, 'Write not allowed')
        listenSocket.sendto(pkg, clientAddress)
        continue

    # Handle read requests
    if rq['opcode'] == 1:

        # First check if filename contains an illegal path
        if (rq['filename'][:3] == '../') or (rq['filename'][0] == '/'):
            pkg = createErrorPackage(2, 'No absolute or upgoing paths allowed')
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

    # Other opcodes or junk just ignored at this point since we are only looping for requests

listenSocket.shutdown(2)
listenSocket.close()