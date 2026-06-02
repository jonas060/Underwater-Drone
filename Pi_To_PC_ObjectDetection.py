import cv2, zmq, time, json
from picamera2 import Picamera2
import ServoKit

W = 640
H = 360     

PI_CAM_INDEX = 0
PC_IP = "192.168.50.187"
FRAME_PORT = 5555
RESULT_PORT = 5556
JPG_QUALITY = 60
RES = (W, H)#(1280, 720)
MOTOR_RESPONSE_FACTOR = 100


#Instantiate Servo Motors Object
Ports = 4
servo = ServoKit.ServoKit(4)

for port in range(Ports):
    servo.reset(port)

ctx = zmq.Context()

#Send Frames to PC
push = ctx.socket(zmq.PUSH)
push.connect(f"tcp://{PC_IP}:{FRAME_PORT}")
             
#Receive Results from PC
sub = ctx.socket(zmq.SUB)
#sub.connect(f"tcp://{PC_IP}:{FRAME_PORT}")
sub.connect(f"tcp://{PC_IP}:{RESULT_PORT}")
sub.setsockopt_string(zmq.SUBSCRIBE, "")
time.sleep(0.2) #Allow for warm-up delay

poller = zmq.Poller()
poller.register(sub, zmq.POLLIN)

#Check to see if both camera are being accessed by the Raspberry Pi 5.
try:
    cams = Picamera2.global_camera_info()
    for i, c in enumerate(cams):
        print(i, c)
except:
    print("Cameras are not being accessed! Update /boot/firmware/config.txt")

#PiCamera 0 Setup
picam_0 = Picamera2(camera_num = 0)
config_picam_0 = picam_0.create_video_configuration(
    main = {"size": RES, "format" : "RGB888"}, controls = {"FrameRate": 30})
picam_0.configure(config_picam_0)
picam_0.start()

#PiCamera 1 setup
picam_1 = Picamera2(camera_num = 1)
config_picam_1 = picam_1.create_video_configuration(
    main = {"size": RES, "format" : "RGB888"}, controls = {"FrameRate": 30})
picam_1.configure(config_picam_1)
picam_1.start()

frame_id = 0

count = 0
t0_0 = time.time()

x1_0, y1_0, x2_0, y2_0 = [None, None, None, None]
x1_1, y1_1, x2_1, y2_1 = [None, None, None, None]

try:
    while(True):
        frame_id += 1
        t0 = time.time()
        
        time_capture_0 = time.perf_counter()
        #Picamera2 returns RGB; if you need BGR on Pi for any reason, convert.
        #For OpenCV ops on the Pi, convert like this:
        #frame_bgr = cv2.cvtColor(original_frame, cv2.COLOR_RGB2BGR)
        image_cam_0 = picam_0.capture_array()
        image_cam_1 = picam_1.capture_array()
        time_capture_1 = time.perf_counter()

        #JPEG encode (tune quality for bandwith/latency)
        ok_cam_0, jpg_cam_0 = cv2.imencode(".jpg", image_cam_0, [int(cv2.IMWRITE_JPEG_QUALITY), JPG_QUALITY])
        ok_cam_1, jpg_cam_1 = cv2.imencode(".jpg", image_cam_1, [int(cv2.IMWRITE_JPEG_QUALITY), JPG_QUALITY])
        #print(jpg_cam_1)
        #print(ok_cam_1)
        time_encode = time.perf_counter()

        if not ok_cam_0 or not ok_cam_1:
            continue
        
        #Send multipart: [cam, frame_id, timestamp, jpg_bytes]
        push.send_multipart([
            "cam0".encode(),
            str(frame_id).encode(),
            str(t0).encode(),
            jpg_cam_0.tobytes()
            ])
        
        push.send_multipart([
            "cam1".encode(),
            str(frame_id).encode(),
            str(t0).encode(),
            jpg_cam_1.tobytes()
            ])

        count += 1
        now = time.time()
        time_send = time.perf_counter()
        print(f"capture = {(time_capture_1 - time_capture_0) * 1000:.1f}ms encode = {(time_encode - time_capture_1) * 1000:.1f}ms send = {(time_send - time_encode) * 1000:.1f}ms")
        
        if (now - t0_0) > 2.0:
            print(f"Pi send FPS: {count/(now - t0_0): .1f}")
            count = 0
            t0_0 = now

        #Non-blocking read of latest result(s)
        #(If PC publishes faster than we read, we may get multiple messages).
        while(True):
            events = dict(poller.poll(timeout = 0))
            #print("poll keys:", [id(s) for s in events.keys()], "sub id:", id(sub))
            if events.get(sub) != zmq.POLLIN:
                break
            #if events.get(sub) == zmq.POLLIN:
                #topic, msg = sub.recv_string().split(" ", 1)
                #print("got", topic)
            message = sub.recv_string()
            detections = json.loads(message)
            
            
            #print(message)
#             print(detections)
#             #DETERMINE MOTOR CONTROL HERE

            if(len(detections['detections']) > 0 and detections['camera'] == "cam0"):
                for detect in detections['detections']:
                    #print(detect, " - cam0")
                     #We will need to store Cam 0 and Cam 1 detections.
                     #We will center based upon Cam 0.
                     #We will then perform Triangulation
                    x1_0, y1_0, x2_0, y2_0 = detect['bbox']
            if(len(detections['detections']) > 0 and detections['camera'] == "cam1"):
                for detect in detections['detections']:
                    #print(detect, " - cam1")
                    x1_1, y1_1, x2_1, y2_1 = detect['bbox']
                    
            #If camera(s) need to move to center on object. Find new bounding boxes of
            #closest object of interest for both cam0 and cam1.
                    
            #Determine center pixel for object of interest
                
            if(x1_0 is not None and x1_1 is not None): 
                x_axis_ObjectOfInterest = (x1_0 + x2_0)/2 - W/2
                y_axis_ObjectOfInterest = (y1_0 + y2_0)/2 - H/2
                
                #Get current servo angles
                current_angle_pan = int(servo.getAngle(1))
                current_angle_tilt = int(servo.getAngle(0))
        
                if(x_axis_ObjectOfInterest > 60): #If the camera center orientation is within 20 pixels of True Center for the object of interest, do not pan camera.
                    angle_update = x_axis_ObjectOfInterest/MOTOR_RESPONSE_FACTOR
                    servo.setAngle(1, current_angle_pan + max(2, angle_update))
                        
                #If the object of interest is not centered on our screen to the left pan our camera to the left (counter-clockwise).
                if(x_axis_ObjectOfInterest < -60):
                    angle_update = x_axis_ObjectOfInterest/MOTOR_RESPONSE_FACTOR
                    servo.setAngle(1, current_angle_pan - max(1, angle_update))
                    
                if(y_axis_ObjectOfInterest < -60):
                    #print("Panning Up!")
                    angle_update = y_axis_ObjectOfInterest/MOTOR_RESPONSE_FACTOR
                    servo.setAngle(0, current_angle_tilt + max(2, angle_update))
                    
                if(y_axis_ObjectOfInterest > 60):
                    #print("Panning Down!")
                    angle_update = y_axis_ObjectOfInterest/MOTOR_RESPONSE_FACTOR
                    servo.setAngle(0, current_angle_tilt - max(1, angle_update))
            
            
            
except KeyboardInterrupt:
    pass

finally:
    picam_0.stop()
    picam_1.stop()
    push.close()
    sub.close()
    ctx.term()
        