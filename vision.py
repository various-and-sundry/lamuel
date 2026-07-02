# MIT License
# Copyright (c) 2019-2022 JetsonHacks

import cv2
import numpy as np

servo_x = 0
servo_y = 0

def gstreamer_pipeline(
    sensor_id=0,
    capture_width=1920,
    capture_height=1080,
    display_width=960,
    display_height=540,
    framerate=30,
    flip_method=0,
):
    return (
        "nvarguscamerasrc sensor-id=%d ! "
        "video/x-raw(memory:NVMM), width=(int)%d, height=(int)%d, framerate=(fraction)%d/1 ! "
        "nvvidconv flip-method=%d ! "
        "video/x-raw, width=(int)%d, height=(int)%d, format=(string)BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink"
        % (
            sensor_id,
            capture_width,
            capture_height,
            framerate,
            flip_method,
            display_width,
            display_height,
        )
    )

def findRelativePossition(x_center, y_center, frame_width, frame_height):
    global servo_x

    # Calculate the center of the image
    image_center_x = frame_width / 2
    image_center_y = frame_height / 2

    # Calculate relative position
    relative_x = image_center_x - x_center
    relative_y = image_center_y - y_center

    # Print the relative coordinates
    print(f"Relative Position - X: {relative_x}, Y: {relative_y}")

    #TODO add servo code here

    # If servo is not past left bound and target is more than 100 px left
    if (servo_x < 80 and relative_x > 100) :
        # Move with speed proportional to target distance from center
        servo_x += relative_x / 400
        print("MOVING LEFT")

    # If servo is not past right bound and target is more than 100 px right
    if (servo_x > -80 and relative_x < -100) :
        # Move with speed proportional to target distance from center
        servo_x += relative_x / 400
        print("MOVING RIGHT")



def show_camera():
    window_title = "CSI Camera"
    print(gstreamer_pipeline(flip_method=0))
    video_capture = cv2.VideoCapture(gstreamer_pipeline(flip_method=0), cv2.CAP_GSTREAMER)

    # Load the Haar Cascade classifier for face detection
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    # Initialize variables for motion tracking
    last_frame = None

    if video_capture.isOpened():
        try:
            window_handle = cv2.namedWindow(window_title, cv2.WINDOW_AUTOSIZE)
            frame_width = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

            while True:
                ret_val, frame = video_capture.read()
                if not ret_val:
                    print("Error: Unable to read frame")
                    break

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
                        findRelativePossition(face_center_x, face_center_y, frame_width, frame_height)
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
                                findRelativePossition(motion_center_x, motion_center_y, frame_width, frame_height)

                    # Update the last frame
                    last_frame = gray_frame

                # Display the frame with detected faces or motion tracking
                if cv2.getWindowProperty(window_title, cv2.WND_PROP_AUTOSIZE) >= 0:
                    cv2.imshow(window_title, frame)
                else:
                    break

                keyCode = cv2.waitKey(1) & 0xFF
                if keyCode == 27 or keyCode == ord('q'):
                    break
        finally:
            video_capture.release()
            cv2.destroyAllWindows()
    else:
        print("Error: Unable to open camera")

if __name__ == "__main__":
    show_camera()

