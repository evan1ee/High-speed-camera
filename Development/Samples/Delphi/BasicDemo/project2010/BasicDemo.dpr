program BasicDemo;

uses
  Forms,
  IMVDefines in '..\src\IMVDefines.pas',
  Main in '..\src\Main.pas' {Form1},
  IMVApi in '..\src\IMVApi.pas';

{$R *.res}

begin
  Application.Initialize;
  Application.MainFormOnTaskbar := True;
  Application.CreateForm(TForm1, Form1);
  Application.Run;
end.
