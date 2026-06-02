import cv2
from ultralytics import YOLO
from picamera2 import Picamera2
import time
import ServoKit

#Check to see if both camera are being accessed by the Raspberry Pi 5.
cams = Picamera2.global_camera_info()
for i, c in enumerate(cams):
    print(i, c)

#Instantiate Camera Object
piCam = Picamera2(camera_num = 0)
piCam_IMX708 = Picamera2(camera_num = 1)

#Instantiate Servo Motors Object
Ports = 4
servo = ServoKit.ServoKit(4)

for port in range(Ports):
    servo.reset(port)

W=1280
H=720
CONFIDENCE_THRESHOLD = 0.1
MOTOR_RESPONSE_FACTOR = 100

RES = (W,H)
#PiCam 0 Configuration
piCam.preview_configuration.main.size = RES
piCam.preview_configuration.main.format = "RGB888"
piCam.preview_configuration.controls.FrameRate=60
piCam.preview_configuration.align()
piCam.configure("preview")
piCam.start()

#PiCam 1 Configuration
config_PiCam_IMX708 = piCam_IMX708.create_video_configuration(
    main = {"size": RES, "format" : "RGB888"}, controls = {"FrameRate": 60})

piCam_IMX708.configure(config_PiCam_IMX708)
piCam_IMX708.start()

# Load the exported NCNN model (replace with your model path)
model = YOLO("/home/alexjonas-1716/Documents/Computer_Vision/yolo26n_ncnn_model", task = 'detect')
fps=0
tStart=time.time()
# Set resolution for faster processing (optional, adjust based on your needs)

#Build Reverse Map to ensure target is within model classes
#target_id = name_to_id[TARGET_NAME]
Target = "book"
found = False

for ids in model.names.keys():
    class_name = model.names[ids]
    if Target == class_name:
        print("Target Exists!")
        found = True
        target_id = ids
    else:
        continue
if found == False:
    print("Target does not Exist!")
    
while True:
    frame = piCam.capture_array()
    image = piCam.capture_array()
    IMX_image = piCam_IMX708.capture_array()
    
    results = model(frame, conf=0.25, verbose=False)
    
    target_boxes = []
    
    if results[0].boxes is not None and len(results[0].boxes) > 0:
        #Extract tensors
        xyxy = results[0].boxes.xyxy
        class_id_predictions = results[0].boxes.cls
        confidence = results[0].boxes.conf
        
        for index in range(len(results[0].boxes)):
            item_id = int(class_id_predictions[index].item())
            item_confidence = float(confidence[index].item())
            
            #If the item detected is our item of interest and the model is reasonably confident of the item. Create a region of interest (bounding box) around the detected item.
            if(item_id == target_id and item_confidence > CONFIDENCE_THRESHOLD):
                x1, y1, x2, y2 = map(int, xyxy[index].tolist())
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                label = f"{Target} {item_confidence:.2f}"
                cv2.putText(frame, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 3)
                target_boxes.append((x1, y1, x2, y2, item_confidence))
                
        #Retrieve the largest item by area
        if target_boxes is not None and len(target_boxes) > 0:
            biggest = max(target_boxes, key = lambda a: (a[2] - a[0]) * (a[3] - a[1]))
            b_x1, b_y1, b_x2, b_y2, b_item_confidence = biggest
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 3)
            
            #Determine center pixel for object of interest
            x_axis_ObjectOfInterest = (b_x1 + b_x2)/2 - W/2
            y_axis_ObjectOfInterest = (b_y1 + b_y2)/2 - H/2
            
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
    #Retrieve prediction classes
#     boxes = results[0].boxes
#     class_ids = boxes.cls
#     class_names = model.names
#     predicted_classes = [class_names[int(x)] for x in class_ids]
    #print(predicted_classes)
    
    #Include Confidence Scores
#     confidences = boxes.conf
#     for cls, conf in zip(boxes.cls, boxes.conf):
#         print(model.names[int(cls)], float(conf))
    
    image = results[0].plot()  # Plots old boxes on new frame!
    deltaT=time.time()-tStart
    tStart=time.time()
    fps= fps*.8 + .2/deltaT
    cv2.putText(frame, "FPS: "+str(round(fps,1)), (int(W*.01), int(H*.075)), 
            cv2.FONT_HERSHEY_SIMPLEX, H*.002, (0, 0, 255), 2)
    
    # Display the result
    cv2.imshow("YOLO11 Detection", frame)
    cv2.imshow("Image", image)
    cv2.imshow("IMX Image", IMX_image)
 
    # Exit on 'q' key
    if cv2.waitKey(1) == ord('q'):
        break
 
# Cleanup
cv2.destroyAllWindows()