import serial
import time

ser = serial.Serial('/dev/ttyACM0', 9600)
time.sleep(2)  # Wait for the connection to establish

# Send data
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')
ser.write(b'RIGHT\n\r')

# Read response (if applicable)
response = ser.readline()
print(response.decode('utf-8'))

ser.close()

