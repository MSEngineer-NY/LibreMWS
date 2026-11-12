# LibreMWS
Math capabilities and equation rendering added to LibreOffice writer to create Math Work Sheets

LibreMWS - Initial Release - Released 11/12/2026

(Note: LibreMWS was intially developed using Libreoffice 
 Version: 26.2.1.2 (X86_64) on Windows.)
 
I. Install 

LibreMWS requires the installation of the Python Pint Library.
Pint is an open-source Python package used to define, operate, and 
convert physical quantities (magnitudes paired with units of measurement)

To install Pint follow the following instructions:

1. Locate LibreOffice's Python Directory:
	• Open File Explorer and navigate to C:\Program Files\LibreOffice\program (or your custom LibreOffice installation path).

2. Open PowerShell as Administrator:
	• Hold Shift and right-click the program folder, then select Open PowerShell window here.

3. Install pip (if not already installed):
	• Run the following command to download and install pip for LibreOffice's Python:powershell

(Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -UseBasicParsing).Content | .\python.exe -

4. Install Pint:
	• Run the pip command using LibreOffice's embedded Python:powershell
	
.\python.exe -m pip install Pint

II. Install LibreMWS.

Copy libreMWS.py to %appdata%\LibreOffice\4\user\Scripts\python

If the directory does not exist, then create it.

III. To run LibreMWS:

1. Open a new Writer Document,

2. Add equations by seleting Insert -> OLE Object -> Formula Object

3. Inserting the Formula Object will launch LibreOffice Math which will
   allow for the creation of standard math equation.
   
   Values are assigned to Variable usir the ':=' operative.
   
   examples => a:=5  or b:=20 ft
   
4. To enable calcualtion capabilities run Macro "LibreMWS\Calculate Formula" 
   and macro "LibreMWS\StartLiveCalculation"
   
5. Once an equation is created in Math and inserted into Writer, the results
   of the equations should automatically update in Write.
