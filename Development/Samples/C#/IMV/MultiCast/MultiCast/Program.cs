using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MVSDK_Net;

namespace MultiCast
{
    internal class Program
    {
        private static MyCamera cam = new MyCamera();
        private static IMVDefine.IMV_FrameCallBack frameCallBack;
        private static void Main(string[] args)
        {

            Console.WriteLine("SDK Version:{0}", MyCamera.IMV_GetVersion());
            Console.WriteLine("Enum camera device.");

            //枚举设备
            // Discover device
            int res = IMVDefine.IMV_OK;
            IMVDefine.IMV_DeviceList deviceList = new IMVDefine.IMV_DeviceList();
            IMVDefine.IMV_EInterfaceType interfaceTp = IMVDefine.IMV_EInterfaceType.interfaceTypeGige;
            res = MyCamera.IMV_EnumDevices(ref deviceList, (uint) interfaceTp);
            if (res != IMVDefine.IMV_OK)
            {
                Console.WriteLine("Enumeration devices failed! ErrorCode:[{0}]", res);
                Console.Read();
                return;
            }
            if (deviceList.nDevNum < 1)
            {
                Console.WriteLine("No device find. ErrorCode:[{0}]", res);
                Console.Read();
                return;
            }

            // 打印设备基本信息
            // Print device info 
            displayDeviceInfo(deviceList);

            int nCamIndex = 0;
            Console.Write("Please input the camera index: ");
            try
            {
                nCamIndex = Convert.ToInt32(Console.ReadLine());
            }
            catch
            {
                Console.WriteLine("Invalid Input!");
                Console.Read();
                return;
            }
            if (nCamIndex > deviceList.nDevNum - 1 || nCamIndex < 0)
            {
                Console.WriteLine("Input Error!");
                Console.Read();
                return;
            }
            do
            {
                // 创建设备句柄
                // Create Device Handle
                res = cam.IMV_CreateHandle(IMVDefine.IMV_ECreateHandleMode.modeByIndex, nCamIndex);
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Create devHandle failed! ErrorCode[{0}]", res);
                    break;
                }

                Console.WriteLine("Select Control Mode(c) or Monitor Mode(m).");

                char mode = '\0';
                do
                {
                    var input = Console.ReadKey().KeyChar;
                    mode = char.ToLower(input); // 统一转为小写，简化判断
                } while (mode != 'c' && mode != 'm');
                bool isControlMode = (mode == 'c');

                Console.WriteLine("\nOpen camera device.");

                // 打开相机设备 
                // Connect to camera 
                if(isControlMode)
                {
                    res = cam.IMV_OpenEx(IMVDefine.IMV_ECameraAccessPermission.accessPermissionControl);
                }
                else
                {
                    res = cam.IMV_OpenEx(IMVDefine.IMV_ECameraAccessPermission.accessPermissionMonitor);
                }
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Open camera failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 指定组播ip,如239.192.1.1
                // Specify multicast IP, such as 239.192.1.1
                string strIp = "239.192.1.1";
                uint result = ConvertIpToUInt32(strIp);

                if (result != 0 || IsValidIpString(strIp))
                {
                    Console.WriteLine("IP address {0} converted to uint: {1} (0x{2:X8})", strIp, result, result);
                }
                else
                {
                    Console.WriteLine("Invalid IP address format");
                }

                IMVDefine.IMV_TransMission_Type transmissionType = new IMVDefine.IMV_TransMission_Type();
                transmissionType.eTransmissionType = IMVDefine.IMV_TransmissionType.transTypeMulticast;
                transmissionType.nDesIp = result;
                transmissionType.nDesPort = 1042;
                // 设置传输类型
                // Set transmission type
                res = cam.IMV_GIGE_SetTransmissionType(transmissionType);
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Set TransmissionType failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 自由拉流
                // set TriggerMode Off
                res = cam.IMV_SetEnumFeatureSymbol("TriggerMode", "Off");
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Set TriggerMode failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 注册数据帧回调函数
                // Register data frame callback function
                frameCallBack = onGetFrame;
                res = cam.IMV_AttachGrabbing(frameCallBack, IntPtr.Zero);
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Attach grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 开始拉流 
                // Start grabbing 
                res = cam.IMV_StartGrabbing();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Start grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 取图2秒
                // get frame 2 seconds
                Thread.Sleep(2000);

                // 停止拉流 
                // Stop grabbing 
                res = cam.IMV_StopGrabbing();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Stop grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }
        
                //关闭相机
                //Close camera 
                res = cam.IMV_Close();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Close camera failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 销毁设备句柄
                // Destroy Device Handle
                res = cam.IMV_DestroyHandle();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Destroy camera failed! ErrorCode[{0}]", res);
                    break;
                }
            } while (false);

            if (res != IMVDefine.IMV_OK)
            {
                // 销毁设备句柄
                // Destroy Device Handle
                res = cam.IMV_DestroyHandle();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Destroy camera failed! ErrorCode[{0}]", res);
                }
            }

            Console.WriteLine("Press enter to exit");
            Console.Read();
        }

        // 数据帧回调函数
        // Data frame callback function
        private static void onGetFrame(ref IMVDefine.IMV_Frame frame, IntPtr pUser)
        {
            if (frame.frameHandle == IntPtr.Zero)
            {
                Console.WriteLine("frame is NULL");
                return;
            }
            Console.WriteLine("Get frame blockId = {0}", frame.frameInfo.blockId);
        }

        // 验证字符串是否为合法 IPv4 地址格式
        // Verify if the string is a valid IPv4 address format
        static bool IsValidIpString(string ip)
        {
            if (string.IsNullOrEmpty(ip)) return false;

            string[] parts = ip.Split('.');
            if (parts.Length != 4) return false;

            foreach (string part in parts)
            {
                uint num = 0;
                if (!uint.TryParse(part, out num) || num > 255)
                    return false;
            }

            return true;
        }

        // 将 IPv4 字符串转换为 uint（大端字节序）
        // Convert IPv4 string to uint (Big-Endian)
        static uint ConvertIpToUInt32(string ip)
        {
            if (!IsValidIpString(ip))
                return 0; // 返回 0 表示无效 Return 0 for invalid IP

            string[] parts = ip.Split('.');

            uint nIp1 = uint.Parse(parts[0]);
            uint nIp2 = uint.Parse(parts[1]);
            uint nIp3 = uint.Parse(parts[2]);
            uint nIp4 = uint.Parse(parts[3]);

            // 按大端字节序拼接：A.B.C.D -> 0xAABBCCDD
            // Big-Endian concatenation: A.B.C.D -> 0xAABBCCDD
            return (nIp1 << 24) | (nIp2 << 16) | (nIp3 << 8) | nIp4;
        }

        #region 展示设备列表

        private static void displayDeviceInfo(IMVDefine.IMV_DeviceList deviceInfoList)
        {

            Console.WriteLine("Enum device size : {0}\n", deviceInfoList.nDevNum);
            for (int i = 0; i < deviceInfoList.nDevNum; i++)
            {
                IMVDefine.IMV_DeviceInfo deviceInfo =
                    (IMVDefine.IMV_DeviceInfo)
                        Marshal.PtrToStructure(
                            deviceInfoList.pDevInfo + Marshal.SizeOf(typeof(IMVDefine.IMV_DeviceInfo)) * i,
                            typeof(IMVDefine.IMV_DeviceInfo));

                // 相机设备列表的索引
                // Device index in device list
                Console.WriteLine("Camera index : {0}", i);
                // 接口类型（GigE，U3V，CL，PCIe）
                // Interface type 
                Console.WriteLine("nInterfaceType : {0}", deviceInfo.nInterfaceType);
                // 设备ID信息
                // Device ID
                Console.WriteLine("cameraKey : {0}", deviceInfo.cameraKey);
                // 设备的型号信息
                // Device model name
                Console.WriteLine("modelName : {0}", deviceInfo.modelName);
                // 设备的序列号
                // Device serial number
                Console.WriteLine("serialNumber : {0}", deviceInfo.serialNumber);

                if (deviceInfo.nCameraType == IMVDefine.IMV_ECameraType.typeGigeCamera)
                {
                    IMVDefine.IMV_GigEDeviceInfo gigEDeviceInfo =
                        (IMVDefine.IMV_GigEDeviceInfo)
                            ByteToStruct(deviceInfo.deviceSpecificInfo.gigeDeviceInfo,
                                typeof(IMVDefine.IMV_GigEDeviceInfo));

                    Console.WriteLine("ipAddress : {0}", gigEDeviceInfo.ipAddress);
                }
                Console.WriteLine();
            }

        }

        public static object ByteToStruct(Byte[] bytes, Type type)
        {
            int size = Marshal.SizeOf(type);
            if (size > bytes.Length)
            {
                return null;
            }

            // 分配结构体内存空间
            IntPtr structPtr = Marshal.AllocHGlobal(size);

            // 将byte数组拷贝到分配好的内存空间
            Marshal.Copy(bytes, 0, structPtr, size);

            // 将内存空间转换为目标结构体
            object obj = Marshal.PtrToStructure(structPtr, type);

            // 释放内存空间
            Marshal.FreeHGlobal(structPtr);

            return obj;
        }

        #endregion
    }
}
