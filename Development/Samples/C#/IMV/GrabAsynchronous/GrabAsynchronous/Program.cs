using System;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Threading;
using MVSDK_Net;

namespace GrabAsynchronous
{
    internal class Program
    {
        public static MyCamera cam = new MyCamera();
        public static readonly int Max_Count = 2;              //ch:队列缓存区大小,可根据实际情况调整大小 en:The size of the queue cache area can be adjusted according to the actual situation
        public static IMVDefine.IMV_FrameCallBack frameCallBack;
        public static bool g_isExitThread = false;

        /// <summary>
        /// 指针之间进行数据拷贝
        /// </summary>
        /// <param name="pDst">目标地址</param>
        /// <param name="pSrc">源地址</param>
        /// <param name="len">拷贝数据长度</param>
        [DllImport("Kernel32.dll", EntryPoint = "RtlMoveMemory")]
        internal static extern void CopyMemory(IntPtr pDst, IntPtr pSrc, int len);
        public struct FrameInfo
        {
            public ulong blockId;    // 帧 ID / Frame ID
            public uint width;       // 宽度 / Width
            public uint height;      // 高度 / Height
            public uint size;        // 数据大小 / Data size
            public IntPtr data;      // 非托管内存指针 / Unmanaged memory pointer
        }

        public class FrameQueue : IDisposable
        {
            private FrameInfo[] qFrames;
            private int qCurrentSize;
            private int start;
            private int end;
            private int qMaxlen;
            private bool disposed = false;
            private uint frameBufferSize;
            private object lockObj = new object();

            public FrameQueue()
            {
                qCurrentSize = 0;
                start = 0;
                end = 0;
                qMaxlen = 0;
                qFrames = null;
                frameBufferSize = 0;
            }

            /// <summary>
            /// 初始化帧队列
            /// Initialize the frame queue
            /// </summary>
            /// <param name="nBufCount">缓冲区帧数量 / Number of buffer frames</param>
            /// <param name="nImageSize">每帧图像大小（字节）/ Size of each image (bytes)</param>
            /// <returns>0=成功，-1=失败 / 0=Success, -1=Failure</returns>
            public int Initialize(int nBufCount,uint nImageSize)
            {
                if (nBufCount <= 0 || nImageSize == 0)
                {
                    Console.WriteLine("Invalid buffer count or image size.");
                    return -1;
                }
                ReleaseUnmanagedResources();

                qMaxlen = nBufCount;
                qFrames = new FrameInfo[nBufCount];
                frameBufferSize = nImageSize;

                for (int i = 0; i < nBufCount; i++)
                {
                    qFrames[i].width = 0;
                    qFrames[i].height = 0;
                    qFrames[i].blockId = 0;
                    qFrames[i].size = 0;
                    qFrames[i].data = Marshal.AllocHGlobal((int)nImageSize);
                    if (qFrames[i].data == IntPtr.Zero)
                    {
                        ReleaseUnmanagedResources();
                        Console.WriteLine("qFrames is null");
                        return -1;
                    }
                }
                qCurrentSize = 0;
                start = 0;
                end = 0;
                return 0;
            }

            /// <summary>
            /// 释放所有非托管内存
            /// Release all unmanaged memory
            /// </summary>
            private void ReleaseUnmanagedResources()
            {
                if (qFrames != null)
                {
                    for (int i = 0; i < qFrames.Length; i++)
                    {
                        if (qFrames[i].data != IntPtr.Zero)
                        {
                            Marshal.FreeHGlobal(qFrames[i].data);
                            qFrames[i].data = IntPtr.Zero;
                        }
                    }
                    qFrames = null;
                }
            }

            /// <summary>
            /// 向队列推入一帧图像
            /// Push a frame into the queue
            /// </summary>
            /// <param name="nBlockID">帧 ID / Frame ID</param>
            /// <param name="nWidth">图像宽度 / Width</param>
            /// <param name="nHeight">图像高度 / Height</param>
            /// <param name="pData">源图像数据指针 / Source image data pointer</param>
            /// <param name="nSize">数据大小 / Data size</param>
            /// <returns>0=成功，-1=失败</returns>
            public int push(ulong nBlockID, uint nWidth, uint nHeight, IntPtr pData, uint nSize)
            {
                if (pData == IntPtr.Zero || nSize == 0)
                {
                    Console.WriteLine("Invalid input data in Push");
                    return -1;
                }

                lock(lockObj)
                {
                    if (qCurrentSize == qMaxlen)
                    {
                        Console.WriteLine("There are no empty positions in the queue");
                        return -1;
                    }

                    if (nSize > frameBufferSize)
                    {
                        Console.WriteLine("Input data size exceeds frame buffer size.");
                        return -1;
                    }

                    qFrames[end].blockId = nBlockID;
                    qFrames[end].width = nWidth;
                    qFrames[end].height = nHeight;
                    qFrames[end].size = nSize;

                    if (qFrames[end].data != IntPtr.Zero)
                    {
                        CopyMemory(qFrames[end].data, pData, (int)nSize);
                    }
                    else
                    {
                        Console.WriteLine("data invalid");
                        return -1;
                    }

                    end = (end + 1) % qMaxlen;
                    qCurrentSize++;
                    return 0;
                }                             
            }

            /// <summary>
            /// 从队列弹出一帧图像
            /// </summary>
            /// <param name="frame">输出帧信息</param>
            /// <param name="pData">目标缓冲区（必须足够大）</param>
            /// <param name="bufSize">目标缓冲区大小</param>
            /// <returns>0=成功, -1=队列空, -2=缓冲区太小</returns>
            public int pop(ref FrameInfo frame, IntPtr pData, uint bufSize)
            {
                if (pData == IntPtr.Zero)
                {
                    Console.WriteLine("Destination pointer is null in Pop");
                    return -1;
                }

                lock (lockObj)
                {

                    if (qCurrentSize == 0)
                    {
                        Console.WriteLine("The queue has no data");
                        return -1;
                    }

                    uint size = qFrames[start].size;
                    if (bufSize < size)
                    {
                        Console.WriteLine("Destination buffer too small in Pop");
                        return -2;
                    }

                    frame.blockId = qFrames[start].blockId;
                    frame.width = qFrames[start].width;
                    frame.height = qFrames[start].height;
                    frame.size = qFrames[start].size;

                    if (qFrames[start].data != IntPtr.Zero)
                    {
                        CopyMemory(pData, qFrames[start].data, (int)qFrames[start].size);
                    }
                    else
                    {
                        Console.WriteLine("data is null");
                        return -1;
                    }
                    qCurrentSize--;
                    start = (start + 1) % qMaxlen;
                    return 0;
                }
            }

            #region IDisposable Support
            protected virtual void Dispose(bool disposing)
            {
                if (!disposed)
                {
                    ReleaseUnmanagedResources();

                    if (disposing)
                    {
                    }

                    disposed = true;
                }
            }

            public void Dispose()
            {
                Dispose(true);
                GC.SuppressFinalize(this);
            }
            #endregion
        }

        public static FrameQueue m_queue;

        private static void Main(string[] args)
        {
            m_queue = new FrameQueue();
            Console.WriteLine("SDK Version:{0}", MyCamera.IMV_GetVersion());
            Console.WriteLine("Enum camera device.");

            //枚举设备
            // Discover device
            int res = IMVDefine.IMV_OK;
            IMVDefine.IMV_DeviceList deviceList = new IMVDefine.IMV_DeviceList();
            IMVDefine.IMV_EInterfaceType interfaceTp = IMVDefine.IMV_EInterfaceType.interfaceTypeAll;
            res = MyCamera.IMV_EnumDevices(ref deviceList, (uint)interfaceTp);
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

                Console.WriteLine("Open camera device.");

                // 打开相机设备 
                // Connect to camera 
                res = cam.IMV_Open();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Open camera failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 计算帧大小
                // Calculate frame size
                uint nImageSize = 0;
                res = getFrameSize(ref nImageSize);
                if (res != IMVDefine.IMV_OK || nImageSize <= 0)
                {
                    break;
                }

                //初始化队列
                //Initiation queue
                res = m_queue.Initialize(Max_Count, nImageSize);
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Init frameQueue failed! ErrorCode[{0}]", res);
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
                frameCallBack = new IMVDefine.IMV_FrameCallBack(onGetFrame);
                res = cam.IMV_AttachGrabbing(frameCallBack, IntPtr.Zero);
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Attach grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                Task task = new Task(() => getFrameProc(nImageSize));
                task.Start();

                // 开始拉流 
                // Start grabbing 
                res = cam.IMV_StartGrabbing();
                if (res != IMVDefine.IMV_OK)
                {
                    Console.WriteLine("Start grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                Thread.Sleep(2000);
                g_isExitThread = true;
                task.Wait();

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

            m_queue.Dispose();
            m_queue = null;

            Console.WriteLine("Press enter to exit");
            Console.Read();
        }

        private static int getFrameSize(ref uint nImageSize)
        {
            long width = 0, height = 0;

            int res = cam.IMV_GetIntFeatureValue("Width", ref width);
            if (res != IMVDefine.IMV_OK)
            {
                Console.WriteLine("Get width feature value failed! ErrorCode:[{0}]", res);
                return res;
            }

            res = cam.IMV_GetIntFeatureValue("Height", ref height);
            if (res != IMVDefine.IMV_OK)
            {
                Console.WriteLine("Get height feature value failed! ErrorCode:[{0}]", res);
                return res;
            }

            // 最合适的大小为(宽*高*每个像素占用的字节大小),此处申请源数据为RGB等彩色格式所需大小
            // The most suitable size is (width * height * (byte size occupied by each pixel))
            // The requested source data here is in the required size for color formats such as RGB
            nImageSize = (uint)width * (uint)height * 3;

            return IMVDefine.IMV_OK;
        }

        private static void onGetFrame(ref IMVDefine.IMV_Frame frame, IntPtr pUser)
        {
            int nRet = IMVDefine.IMV_OK;
            if (frame.frameHandle == IntPtr.Zero)
            {
                Console.WriteLine("frame is NULL");
                return;
            }

            nRet = m_queue.push(frame.frameInfo.blockId, frame.frameInfo.width, frame.frameInfo.height, frame.pData,
                frame.frameInfo.size);
            if (nRet != 0)
            {
                Console.WriteLine("Add frame to queue failed! blockId is {0}", frame.frameInfo.blockId);
            }
            else
            {
                Console.WriteLine("Add frame to queue success! blockId is {0}", frame.frameInfo.blockId);
            }
        }

        private static void getFrameProc(uint nImageSize)
        {
            int res = 0;
            FrameInfo frame = new FrameInfo();
            frame.data = Marshal.AllocHGlobal((int)nImageSize);

            while (!g_isExitThread)
            {
                frame.blockId = 0;
                frame.width = 0;
                frame.height = 0;
                frame.size = 0;
                res = m_queue.pop(ref frame, frame.data, nImageSize);
                if (res != 0)
                {
                    Console.WriteLine("Pop failed, maybe no data.");
                    Thread.Sleep(1);
                    continue;
                }
                else
                {
                    Console.WriteLine("Pop success. BlockId is [{0}]", frame.blockId);
                }
            }

            Marshal.FreeHGlobal(frame.data);
            frame.data = IntPtr.Zero;
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
