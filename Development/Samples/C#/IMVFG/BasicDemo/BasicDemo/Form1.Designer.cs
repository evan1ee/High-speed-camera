namespace BasicDemo
{
    partial class Form1
    {
        /// <summary>
        /// 必需的设计器变量。
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary>
        /// 清理所有正在使用的资源。
        /// </summary>
        /// <param name="disposing">如果应释放托管资源，为 true；否则为 false。</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows 窗体设计器生成的代码

        /// <summary>
        /// 设计器支持所需的方法 - 不要
        /// 使用代码编辑器修改此方法的内容。
        /// </summary>
        private void InitializeComponent()
        {
            System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(Form1));
            this.pbImage = new System.Windows.Forms.PictureBox();
            this.btnOpenInterface = new System.Windows.Forms.Button();
            this.btnCloseInterface = new System.Windows.Forms.Button();
            this.cmbInterfaceList = new System.Windows.Forms.ComboBox();
            this.groupBox1 = new System.Windows.Forms.GroupBox();
            this.btnEnumInterfaces = new System.Windows.Forms.Button();
            this.groupBox2 = new System.Windows.Forms.GroupBox();
            this.btnSoftware = new System.Windows.Forms.Button();
            this.chbSoftTrigger = new System.Windows.Forms.CheckBox();
            this.btnStop = new System.Windows.Forms.Button();
            this.btnStart = new System.Windows.Forms.Button();
            this.radioTrigger = new System.Windows.Forms.RadioButton();
            this.radioContinue = new System.Windows.Forms.RadioButton();
            this.groupBox3 = new System.Windows.Forms.GroupBox();
            this.btnSaveBIN = new System.Windows.Forms.Button();
            this.btnSaveBMP = new System.Windows.Forms.Button();
            this.label1 = new System.Windows.Forms.Label();
            this.label2 = new System.Windows.Forms.Label();
            this.cmbDeviceList = new System.Windows.Forms.ComboBox();
            this.groupBox4 = new System.Windows.Forms.GroupBox();
            this.btnEnumDevices = new System.Windows.Forms.Button();
            this.btnOpenDevice = new System.Windows.Forms.Button();
            this.btnCloseDevice = new System.Windows.Forms.Button();
            this.groupBox5 = new System.Windows.Forms.GroupBox();
            this.btnGetInterfaceParam = new System.Windows.Forms.Button();
            this.btnSetInterfaceParam = new System.Windows.Forms.Button();
            this.txtInterfaceHeight = new System.Windows.Forms.TextBox();
            this.txtInterfaceWidth = new System.Windows.Forms.TextBox();
            this.cmbInterfacePixelType = new System.Windows.Forms.ComboBox();
            this.label3 = new System.Windows.Forms.Label();
            this.label4 = new System.Windows.Forms.Label();
            this.label5 = new System.Windows.Forms.Label();
            this.groupBox6 = new System.Windows.Forms.GroupBox();
            this.btnGetDeviceParam = new System.Windows.Forms.Button();
            this.btnSetDeviceParam = new System.Windows.Forms.Button();
            this.txtDeviceGainRaw = new System.Windows.Forms.TextBox();
            this.txtDeviceExposuretime = new System.Windows.Forms.TextBox();
            this.cmbDevicePixelType = new System.Windows.Forms.ComboBox();
            this.label6 = new System.Windows.Forms.Label();
            this.label7 = new System.Windows.Forms.Label();
            this.label8 = new System.Windows.Forms.Label();
            ((System.ComponentModel.ISupportInitialize)(this.pbImage)).BeginInit();
            this.groupBox1.SuspendLayout();
            this.groupBox2.SuspendLayout();
            this.groupBox3.SuspendLayout();
            this.groupBox4.SuspendLayout();
            this.groupBox5.SuspendLayout();
            this.groupBox6.SuspendLayout();
            this.SuspendLayout();
            // 
            // pbImage
            // 
            resources.ApplyResources(this.pbImage, "pbImage");
            this.pbImage.Name = "pbImage";
            this.pbImage.TabStop = false;
            // 
            // btnOpenInterface
            // 
            resources.ApplyResources(this.btnOpenInterface, "btnOpenInterface");
            this.btnOpenInterface.Name = "btnOpenInterface";
            this.btnOpenInterface.UseVisualStyleBackColor = true;
            this.btnOpenInterface.Click += new System.EventHandler(this.btnOpenInterface_Click);
            // 
            // btnCloseInterface
            // 
            resources.ApplyResources(this.btnCloseInterface, "btnCloseInterface");
            this.btnCloseInterface.Name = "btnCloseInterface";
            this.btnCloseInterface.UseVisualStyleBackColor = true;
            this.btnCloseInterface.Click += new System.EventHandler(this.btnCloseInterface_Click);
            // 
            // cmbInterfaceList
            // 
            this.cmbInterfaceList.FormattingEnabled = true;
            resources.ApplyResources(this.cmbInterfaceList, "cmbInterfaceList");
            this.cmbInterfaceList.Name = "cmbInterfaceList";
            this.cmbInterfaceList.SelectedIndexChanged += new System.EventHandler(this.cmbInterfaceList_SelectedIndexChanged);
            // 
            // groupBox1
            // 
            this.groupBox1.Controls.Add(this.btnEnumInterfaces);
            this.groupBox1.Controls.Add(this.btnOpenInterface);
            this.groupBox1.Controls.Add(this.btnCloseInterface);
            resources.ApplyResources(this.groupBox1, "groupBox1");
            this.groupBox1.Name = "groupBox1";
            this.groupBox1.TabStop = false;
            // 
            // btnEnumInterfaces
            // 
            resources.ApplyResources(this.btnEnumInterfaces, "btnEnumInterfaces");
            this.btnEnumInterfaces.Name = "btnEnumInterfaces";
            this.btnEnumInterfaces.UseVisualStyleBackColor = true;
            this.btnEnumInterfaces.Click += new System.EventHandler(this.btnEnumInterfaces_Click);
            // 
            // groupBox2
            // 
            this.groupBox2.Controls.Add(this.btnSoftware);
            this.groupBox2.Controls.Add(this.chbSoftTrigger);
            this.groupBox2.Controls.Add(this.btnStop);
            this.groupBox2.Controls.Add(this.btnStart);
            this.groupBox2.Controls.Add(this.radioTrigger);
            this.groupBox2.Controls.Add(this.radioContinue);
            resources.ApplyResources(this.groupBox2, "groupBox2");
            this.groupBox2.Name = "groupBox2";
            this.groupBox2.TabStop = false;
            // 
            // btnSoftware
            // 
            resources.ApplyResources(this.btnSoftware, "btnSoftware");
            this.btnSoftware.Name = "btnSoftware";
            this.btnSoftware.UseVisualStyleBackColor = true;
            this.btnSoftware.Click += new System.EventHandler(this.btnSoftware_Click);
            // 
            // chbSoftTrigger
            // 
            resources.ApplyResources(this.chbSoftTrigger, "chbSoftTrigger");
            this.chbSoftTrigger.Name = "chbSoftTrigger";
            this.chbSoftTrigger.UseVisualStyleBackColor = true;
            this.chbSoftTrigger.CheckedChanged += new System.EventHandler(this.chbSoftTrigger_CheckedChanged);
            // 
            // btnStop
            // 
            resources.ApplyResources(this.btnStop, "btnStop");
            this.btnStop.Name = "btnStop";
            this.btnStop.UseVisualStyleBackColor = true;
            this.btnStop.Click += new System.EventHandler(this.btnStop_Click);
            // 
            // btnStart
            // 
            resources.ApplyResources(this.btnStart, "btnStart");
            this.btnStart.Name = "btnStart";
            this.btnStart.UseVisualStyleBackColor = true;
            this.btnStart.Click += new System.EventHandler(this.btnStart_Click);
            // 
            // radioTrigger
            // 
            resources.ApplyResources(this.radioTrigger, "radioTrigger");
            this.radioTrigger.Name = "radioTrigger";
            this.radioTrigger.TabStop = true;
            this.radioTrigger.UseVisualStyleBackColor = true;
            this.radioTrigger.CheckedChanged += new System.EventHandler(this.radioTrigger_CheckedChanged);
            // 
            // radioContinue
            // 
            resources.ApplyResources(this.radioContinue, "radioContinue");
            this.radioContinue.Name = "radioContinue";
            this.radioContinue.TabStop = true;
            this.radioContinue.UseVisualStyleBackColor = true;
            this.radioContinue.CheckedChanged += new System.EventHandler(this.radioContinue_CheckedChanged);
            // 
            // groupBox3
            // 
            this.groupBox3.Controls.Add(this.btnSaveBIN);
            this.groupBox3.Controls.Add(this.btnSaveBMP);
            resources.ApplyResources(this.groupBox3, "groupBox3");
            this.groupBox3.Name = "groupBox3";
            this.groupBox3.TabStop = false;
            // 
            // btnSaveBIN
            // 
            resources.ApplyResources(this.btnSaveBIN, "btnSaveBIN");
            this.btnSaveBIN.Name = "btnSaveBIN";
            this.btnSaveBIN.UseVisualStyleBackColor = true;
            this.btnSaveBIN.Click += new System.EventHandler(this.btnSaveBIN_Click);
            // 
            // btnSaveBMP
            // 
            resources.ApplyResources(this.btnSaveBMP, "btnSaveBMP");
            this.btnSaveBMP.Name = "btnSaveBMP";
            this.btnSaveBMP.UseVisualStyleBackColor = true;
            this.btnSaveBMP.Click += new System.EventHandler(this.btnSaveBMP_Click);
            // 
            // label1
            // 
            resources.ApplyResources(this.label1, "label1");
            this.label1.Name = "label1";
            // 
            // label2
            // 
            resources.ApplyResources(this.label2, "label2");
            this.label2.Name = "label2";
            // 
            // cmbDeviceList
            // 
            this.cmbDeviceList.FormattingEnabled = true;
            resources.ApplyResources(this.cmbDeviceList, "cmbDeviceList");
            this.cmbDeviceList.Name = "cmbDeviceList";
            this.cmbDeviceList.SelectedIndexChanged += new System.EventHandler(this.cmbDeviceList_SelectedIndexChanged);
            // 
            // groupBox4
            // 
            this.groupBox4.Controls.Add(this.btnEnumDevices);
            this.groupBox4.Controls.Add(this.btnOpenDevice);
            this.groupBox4.Controls.Add(this.btnCloseDevice);
            resources.ApplyResources(this.groupBox4, "groupBox4");
            this.groupBox4.Name = "groupBox4";
            this.groupBox4.TabStop = false;
            // 
            // btnEnumDevices
            // 
            resources.ApplyResources(this.btnEnumDevices, "btnEnumDevices");
            this.btnEnumDevices.Name = "btnEnumDevices";
            this.btnEnumDevices.UseVisualStyleBackColor = true;
            this.btnEnumDevices.Click += new System.EventHandler(this.btnEnumDevices_Click);
            // 
            // btnOpenDevice
            // 
            resources.ApplyResources(this.btnOpenDevice, "btnOpenDevice");
            this.btnOpenDevice.Name = "btnOpenDevice";
            this.btnOpenDevice.UseVisualStyleBackColor = true;
            this.btnOpenDevice.Click += new System.EventHandler(this.btnOpenDevice_Click);
            // 
            // btnCloseDevice
            // 
            resources.ApplyResources(this.btnCloseDevice, "btnCloseDevice");
            this.btnCloseDevice.Name = "btnCloseDevice";
            this.btnCloseDevice.UseVisualStyleBackColor = true;
            this.btnCloseDevice.Click += new System.EventHandler(this.btnCloseDevice_Click);
            // 
            // groupBox5
            // 
            this.groupBox5.Controls.Add(this.btnGetInterfaceParam);
            this.groupBox5.Controls.Add(this.btnSetInterfaceParam);
            this.groupBox5.Controls.Add(this.txtInterfaceHeight);
            this.groupBox5.Controls.Add(this.txtInterfaceWidth);
            this.groupBox5.Controls.Add(this.cmbInterfacePixelType);
            this.groupBox5.Controls.Add(this.label3);
            this.groupBox5.Controls.Add(this.label4);
            this.groupBox5.Controls.Add(this.label5);
            resources.ApplyResources(this.groupBox5, "groupBox5");
            this.groupBox5.Name = "groupBox5";
            this.groupBox5.TabStop = false;
            // 
            // btnGetInterfaceParam
            // 
            resources.ApplyResources(this.btnGetInterfaceParam, "btnGetInterfaceParam");
            this.btnGetInterfaceParam.Name = "btnGetInterfaceParam";
            this.btnGetInterfaceParam.UseVisualStyleBackColor = true;
            this.btnGetInterfaceParam.Click += new System.EventHandler(this.btnGetInterfaceParam_Click);
            // 
            // btnSetInterfaceParam
            // 
            resources.ApplyResources(this.btnSetInterfaceParam, "btnSetInterfaceParam");
            this.btnSetInterfaceParam.Name = "btnSetInterfaceParam";
            this.btnSetInterfaceParam.UseVisualStyleBackColor = true;
            this.btnSetInterfaceParam.Click += new System.EventHandler(this.btnSetInterfaceParam_Click);
            // 
            // txtInterfaceHeight
            // 
            resources.ApplyResources(this.txtInterfaceHeight, "txtInterfaceHeight");
            this.txtInterfaceHeight.Name = "txtInterfaceHeight";
            // 
            // txtInterfaceWidth
            // 
            resources.ApplyResources(this.txtInterfaceWidth, "txtInterfaceWidth");
            this.txtInterfaceWidth.Name = "txtInterfaceWidth";
            // 
            // cmbInterfacePixelType
            // 
            this.cmbInterfacePixelType.FormattingEnabled = true;
            resources.ApplyResources(this.cmbInterfacePixelType, "cmbInterfacePixelType");
            this.cmbInterfacePixelType.Name = "cmbInterfacePixelType";
            // 
            // label3
            // 
            resources.ApplyResources(this.label3, "label3");
            this.label3.Name = "label3";
            // 
            // label4
            // 
            resources.ApplyResources(this.label4, "label4");
            this.label4.Name = "label4";
            // 
            // label5
            // 
            resources.ApplyResources(this.label5, "label5");
            this.label5.Name = "label5";
            // 
            // groupBox6
            // 
            this.groupBox6.Controls.Add(this.btnGetDeviceParam);
            this.groupBox6.Controls.Add(this.btnSetDeviceParam);
            this.groupBox6.Controls.Add(this.txtDeviceGainRaw);
            this.groupBox6.Controls.Add(this.txtDeviceExposuretime);
            this.groupBox6.Controls.Add(this.cmbDevicePixelType);
            this.groupBox6.Controls.Add(this.label6);
            this.groupBox6.Controls.Add(this.label7);
            this.groupBox6.Controls.Add(this.label8);
            resources.ApplyResources(this.groupBox6, "groupBox6");
            this.groupBox6.Name = "groupBox6";
            this.groupBox6.TabStop = false;
            // 
            // btnGetDeviceParam
            // 
            resources.ApplyResources(this.btnGetDeviceParam, "btnGetDeviceParam");
            this.btnGetDeviceParam.Name = "btnGetDeviceParam";
            this.btnGetDeviceParam.UseVisualStyleBackColor = true;
            this.btnGetDeviceParam.Click += new System.EventHandler(this.btnGetDeviceParam_Click);
            // 
            // btnSetDeviceParam
            // 
            resources.ApplyResources(this.btnSetDeviceParam, "btnSetDeviceParam");
            this.btnSetDeviceParam.Name = "btnSetDeviceParam";
            this.btnSetDeviceParam.UseVisualStyleBackColor = true;
            this.btnSetDeviceParam.Click += new System.EventHandler(this.btnSetDeviceParam_Click);
            // 
            // txtDeviceGainRaw
            // 
            resources.ApplyResources(this.txtDeviceGainRaw, "txtDeviceGainRaw");
            this.txtDeviceGainRaw.Name = "txtDeviceGainRaw";
            // 
            // txtDeviceExposuretime
            // 
            resources.ApplyResources(this.txtDeviceExposuretime, "txtDeviceExposuretime");
            this.txtDeviceExposuretime.Name = "txtDeviceExposuretime";
            // 
            // cmbDevicePixelType
            // 
            this.cmbDevicePixelType.FormattingEnabled = true;
            resources.ApplyResources(this.cmbDevicePixelType, "cmbDevicePixelType");
            this.cmbDevicePixelType.Name = "cmbDevicePixelType";
            // 
            // label6
            // 
            resources.ApplyResources(this.label6, "label6");
            this.label6.Name = "label6";
            // 
            // label7
            // 
            resources.ApplyResources(this.label7, "label7");
            this.label7.Name = "label7";
            // 
            // label8
            // 
            resources.ApplyResources(this.label8, "label8");
            this.label8.Name = "label8";
            // 
            // Form1
            // 
            resources.ApplyResources(this, "$this");
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.Controls.Add(this.groupBox6);
            this.Controls.Add(this.groupBox5);
            this.Controls.Add(this.groupBox4);
            this.Controls.Add(this.cmbDeviceList);
            this.Controls.Add(this.label2);
            this.Controls.Add(this.label1);
            this.Controls.Add(this.groupBox3);
            this.Controls.Add(this.groupBox2);
            this.Controls.Add(this.groupBox1);
            this.Controls.Add(this.cmbInterfaceList);
            this.Controls.Add(this.pbImage);
            this.MaximizeBox = false;
            this.MinimizeBox = false;
            this.Name = "Form1";
            this.Shown += new System.EventHandler(this.Form1_Shown);
            ((System.ComponentModel.ISupportInitialize)(this.pbImage)).EndInit();
            this.groupBox1.ResumeLayout(false);
            this.groupBox2.ResumeLayout(false);
            this.groupBox2.PerformLayout();
            this.groupBox3.ResumeLayout(false);
            this.groupBox4.ResumeLayout(false);
            this.groupBox5.ResumeLayout(false);
            this.groupBox5.PerformLayout();
            this.groupBox6.ResumeLayout(false);
            this.groupBox6.PerformLayout();
            this.ResumeLayout(false);
            this.PerformLayout();

        }

        #endregion

        private System.Windows.Forms.PictureBox pbImage;
        private System.Windows.Forms.Button btnOpenInterface;
        private System.Windows.Forms.Button btnCloseInterface;
        private System.Windows.Forms.ComboBox cmbInterfaceList;
        private System.Windows.Forms.GroupBox groupBox1;
        private System.Windows.Forms.Button btnEnumInterfaces;
        private System.Windows.Forms.GroupBox groupBox2;
        private System.Windows.Forms.RadioButton radioTrigger;
        private System.Windows.Forms.RadioButton radioContinue;
        private System.Windows.Forms.Button btnStop;
        private System.Windows.Forms.Button btnStart;
        private System.Windows.Forms.CheckBox chbSoftTrigger;
        private System.Windows.Forms.Button btnSoftware;
        private System.Windows.Forms.GroupBox groupBox3;
        private System.Windows.Forms.Button btnSaveBIN;
        private System.Windows.Forms.Button btnSaveBMP;
        private System.Windows.Forms.Label label1;
        private System.Windows.Forms.Label label2;
        private System.Windows.Forms.ComboBox cmbDeviceList;
        private System.Windows.Forms.GroupBox groupBox4;
        private System.Windows.Forms.Button btnEnumDevices;
        private System.Windows.Forms.Button btnOpenDevice;
        private System.Windows.Forms.Button btnCloseDevice;
        private System.Windows.Forms.GroupBox groupBox5;
        private System.Windows.Forms.Button btnGetInterfaceParam;
        private System.Windows.Forms.Button btnSetInterfaceParam;
        private System.Windows.Forms.TextBox txtInterfaceHeight;
        private System.Windows.Forms.TextBox txtInterfaceWidth;
        private System.Windows.Forms.ComboBox cmbInterfacePixelType;
        private System.Windows.Forms.Label label3;
        private System.Windows.Forms.Label label4;
        private System.Windows.Forms.Label label5;
        private System.Windows.Forms.GroupBox groupBox6;
        private System.Windows.Forms.Button btnGetDeviceParam;
        private System.Windows.Forms.Button btnSetDeviceParam;
        private System.Windows.Forms.TextBox txtDeviceGainRaw;
        private System.Windows.Forms.TextBox txtDeviceExposuretime;
        private System.Windows.Forms.ComboBox cmbDevicePixelType;
        private System.Windows.Forms.Label label6;
        private System.Windows.Forms.Label label7;
        private System.Windows.Forms.Label label8;
    }
}

