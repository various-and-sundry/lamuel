import cv2
import time
import serial
import os
import subprocess

def show_camera():
    window_title = "USB Camera"

    # Initialize video capture from /dev/video1
    video_capture = cv2.VideoCapture(0)  # '0' is usually the default for the first camera, '/dev/video1' can also be used depending on your system setup

    if not video_capture.isOpened():
        print("Error: Unable to open camera")
        return

    # Load the Haar Cascade classifier for face detection
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    # Initialize variables for motion tracking
    last_frame = None

    while True:
        ret_val, frame = video_capture.read()
        if not ret_val:
            print("Error: Unable to read frame")
            break

        # Check if /tmp/GETIMG exists
        getimg_path = '/tmp/GETIMG'
        if os.path.exists(getimg_path):

            subprocess.run(['mpv', 'camera_sound.mp3'])

            # Save the current frame to /tmp/image.jpg
            cv2.imwrite('/tmp/image.jpg', frame)
            print(f'Current frame saved to /tmp/image.jpg.')

            # Delete /tmp/GETIMG
            os.remove(getimg_path)
            print(f'The file {getimg_path} has been deleted.')

        # Convert the frame to grayscale for face detection
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect faces in the frame
        faces = face_cascade.detectMultiScale(gray_frame, scaleFactor=1.1, minNeighbors=5)

        if len(faces) > 0:
            # If faces are detected, draw rectangles around them
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                # Calculate the center of the face
                face_center_x = x + w // 2
                face_center_y = y + h // 2
                findRelativePossition(face_center_x, face_center_y, frame.shape[1], frame.shape[0])
        else:
            # If no faces are detected, perform motion tracking
            if last_frame is not None:
                # Convert the current frame to grayscale
                gray_current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # Compute the absolute difference between the current frame and the last frame
                frame_diff = cv2.absdiff(last_frame, gray_current)

                # Threshold the difference to get the motion areas
                _, thresh = cv2.threshold(frame_diff, 30, 255, cv2.THRESH_BINARY)

                # Find contours of the motion areas
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                if contours:
                    # Find the largest contour based on area
                    largest_contour = max(contours, key=cv2.contourArea)

                    # Draw a rectangle around the largest contour
                    if cv2.contourArea(largest_contour) > 500:  # Minimum area to consider as motion
                        (x, y, w, h) = cv2.boundingRect(largest_contour)
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                        # Calculate the center of the motion area
                        motion_center_x = x + w // 2
                        motion_center_y = y + h // 2
                        findRelativePossition(motion_center_x, motion_center_y, frame.shape[1], frame.shape[0])

            # Update the last frame
            last_frame = gray_frame

        # Resize the image to fit the screen
        resized_image = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)

        # Display the frame with detected faces or motion tracking
        # Check if the DISPLAY environment variable is set


        '''
        cv2.imshow(window_title, resized_image)

        keyCode = cv2.waitKey(1) & 0xFF
        if keyCode == 27 or keyCode == ord('q'):
            break

        video_capture.release()
        cv2.destroyAllWindows()
        '''
        


def findRelativePossition(x, y, width, height):
    global average_relative_x
    global average_relative_y
    global loop_count

    loop_count = loop_count + 1

    # Center of the frame
    center_x = width // 2
    center_y = height // 2

    relative_x = -(x - center_x)
    relative_y = -(y - center_y)

    average_relative_x = (average_relative_x * 4 + relative_x) / 5
    average_relative_y = (average_relative_y * 4 + relative_y) / 5

    print(f"X: {relative_x}, Y: {relative_y}")

    if loop_count > 4:
        if abs(relative_x) > 40 and abs(average_relative_x) > 40:
            int_x = int(average_relative_x / 20)
            message = 'X:' + str(int_x) + '\n\r'
            print(message)
            ser.write(message.encode())
            time.sleep(abs(average_relative_x / 300))
            ser.flushInput()
            ser.flushOutput()
            loop_count = 0

        elif abs(relative_y) > 40 and abs(average_relative_y) > 40:
            int_y = int(average_relative_y / 20)
            message = 'Y:' + str(int_y) + '\n\r'
            print(message)
            ser.write(message.encode())
            time.sleep(abs(average_relative_y / 300))
            ser.flushInput()
            ser.flushOutput()
            loop_count = 0

        else:
            loop_count = 0

# Global variable for servo control simulation
servo_x = 0
average_relative_x = 0
average_relative_y = 0
loop_count = 0

if __name__ == "__main__":
    ser = serial.Serial('/dev/ttyACM0', 9600)
    time.sleep(2)  # Wait for the connection to establish
    show_camera()

