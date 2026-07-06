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
            this.btnOpen = new System.Windows.Forms.Button();
            this.btnClose = new System.Windows.Forms.Button();
            this.cbDeviceInfos = new System.Windows.Forms.ComboBox();
            this.groupBox1 = new System.Windows.Forms.GroupBox();
            this.btnEnumDevices = new System.Windows.Forms.Button();
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
            this.groupBox4 = new System.Windows.Forms.GroupBox();
            this.btnGetParam = new System.Windows.Forms.Button();
            this.btnSetParam = new System.Windows.Forms.Button();
            this.txtGainRaw = new System.Windows.Forms.TextBox();
            this.txtExposuretime = new System.Windows.Forms.TextBox();
            this.cbPixelType = new System.Windows.Forms.ComboBox();
            this.label3 = new System.Windows.Forms.Label();
            this.label2 = new System.Windows.Forms.Label();
            this.label1 = new System.Windows.Forms.Label();
            ((System.ComponentModel.ISupportInitialize)(this.pbImage)).BeginInit();
            this.groupBox1.SuspendLayout();
            this.groupBox2.SuspendLayout();
            this.groupBox3.SuspendLayout();
            this.groupBox4.SuspendLayout();
            this.SuspendLayout();
            // 
            // pbImage
            // 
            resources.ApplyResources(this.pbImage, "pbImage");
            this.pbImage.Name = "pbImage";
            this.pbImage.TabStop = false;
            // 
            // btnOpen
            // 
            resources.ApplyResources(this.btnOpen, "btnOpen");
            this.btnOpen.Name = "btnOpen";
            this.btnOpen.UseVisualStyleBackColor = true;
            this.btnOpen.Click += new System.EventHandler(this.btnOpen_Click);
            // 
            // btnClose
            // 
            resources.ApplyResources(this.btnClose, "btnClose");
            this.btnClose.Name = "btnClose";
            this.btnClose.UseVisualStyleBackColor = true;
            this.btnClose.Click += new System.EventHandler(this.btnClose_Click);
            // 
            // cbDeviceInfos
            // 
            resources.ApplyResources(this.cbDeviceInfos, "cbDeviceInfos");
            this.cbDeviceInfos.FormattingEnabled = true;
            this.cbDeviceInfos.Name = "cbDeviceInfos";
            // 
            // groupBox1
            // 
            resources.ApplyResources(this.groupBox1, "groupBox1");
            this.groupBox1.Controls.Add(this.btnEnumDevices);
            this.groupBox1.Controls.Add(this.btnOpen);
            this.groupBox1.Controls.Add(this.btnClose);
            this.groupBox1.Name = "groupBox1";
            this.groupBox1.TabStop = false;
            // 
            // btnEnumDevices
            // 
            resources.ApplyResources(this.btnEnumDevices, "btnEnumDevices");
            this.btnEnumDevices.Name = "btnEnumDevices";
            this.btnEnumDevices.UseVisualStyleBackColor = true;
            this.btnEnumDevices.Click += new System.EventHandler(this.btnEnumDevices_Click);
            // 
            // groupBox2
            // 
            resources.ApplyResources(this.groupBox2, "groupBox2");
            this.groupBox2.Controls.Add(this.btnSoftware);
            this.groupBox2.Controls.Add(this.chbSoftTrigger);
            this.groupBox2.Controls.Add(this.btnStop);
            this.groupBox2.Controls.Add(this.btnStart);
            this.groupBox2.Controls.Add(this.radioTrigger);
            this.groupBox2.Controls.Add(this.radioContinue);
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
            resources.ApplyResources(this.groupBox3, "groupBox3");
            this.groupBox3.Controls.Add(this.btnSaveBIN);
            this.groupBox3.Controls.Add(this.btnSaveBMP);
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
            // groupBox4
            // 
            resources.ApplyResources(this.groupBox4, "groupBox4");
            this.groupBox4.Controls.Add(this.btnGetParam);
            this.groupBox4.Controls.Add(this.btnSetParam);
            this.groupBox4.Controls.Add(this.txtGainRaw);
            this.groupBox4.Controls.Add(this.txtExposuretime);
            this.groupBox4.Controls.Add(this.cbPixelType);
            this.groupBox4.Controls.Add(this.label3);
            this.groupBox4.Controls.Add(this.label2);
            this.groupBox4.Controls.Add(this.label1);
            this.groupBox4.Name = "groupBox4";
            this.groupBox4.TabStop = false;
            // 
            // btnGetParam
            // 
            resources.ApplyResources(this.btnGetParam, "btnGetParam");
            this.btnGetParam.Name = "btnGetParam";
            this.btnGetParam.UseVisualStyleBackColor = true;
            this.btnGetParam.Click += new System.EventHandler(this.btnGetParam_Click);
            // 
            // btnSetParam
            // 
            resources.ApplyResources(this.btnSetParam, "btnSetParam");
            this.btnSetParam.Name = "btnSetParam";
            this.btnSetParam.UseVisualStyleBackColor = true;
            this.btnSetParam.Click += new System.EventHandler(this.btnSetParam_Click);
            // 
            // txtGainRaw
            // 
            resources.ApplyResources(this.txtGainRaw, "txtGainRaw");
            this.txtGainRaw.Name = "txtGainRaw";
            // 
            // txtExposuretime
            // 
            resources.ApplyResources(this.txtExposuretime, "txtExposuretime");
            this.txtExposuretime.Name = "txtExposuretime";
            // 
            // cbPixelType
            // 
            resources.ApplyResources(this.cbPixelType, "cbPixelType");
            this.cbPixelType.FormattingEnabled = true;
            this.cbPixelType.Name = "cbPixelType";
            // 
            // label3
            // 
            resources.ApplyResources(this.label3, "label3");
            this.label3.Name = "label3";
            // 
            // label2
            // 
            resources.ApplyResources(this.label2, "label2");
            this.label2.Name = "label2";
            // 
            // label1
            // 
            resources.ApplyResources(this.label1, "label1");
            this.label1.Name = "label1";
            // 
            // Form1
            // 
            resources.ApplyResources(this, "$this");
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.Controls.Add(this.groupBox4);
            this.Controls.Add(this.groupBox3);
            this.Controls.Add(this.groupBox2);
            this.Controls.Add(this.groupBox1);
            this.Controls.Add(this.cbDeviceInfos);
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
            this.groupBox4.PerformLayout();
            this.ResumeLayout(false);

        }

        #endregion

        private System.Windows.Forms.PictureBox pbImage;
        private System.Windows.Forms.Button btnOpen;
        private System.Windows.Forms.Button btnClose;
        private System.Windows.Forms.ComboBox cbDeviceInfos;
        private System.Windows.Forms.GroupBox groupBox1;
        private System.Windows.Forms.Button btnEnumDevices;
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
        private System.Windows.Forms.GroupBox groupBox4;
        private System.Windows.Forms.Label label3;
        private System.Windows.Forms.Label label2;
        private System.Windows.Forms.Label label1;
        private System.Windows.Forms.TextBox txtGainRaw;
        private System.Windows.Forms.TextBox txtExposuretime;
        private System.Windows.Forms.ComboBox cbPixelType;
        private System.Windows.Forms.Button btnSetParam;
        private System.Windows.Forms.Button btnGetParam;
    }
}

