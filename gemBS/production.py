#!/usr/bin/env python
"""Production pipelines"""
import os
import re
import logging
import json
import sys
from sys import exit
import subprocess
import threading as th

from utils import Command, CommandException, makeFileName
from reportStats import LaneStats,SampleStats

import gemBS
import report
import sphinx
import bsCallReports


class Fli(object):
    
    def __init__(self):
        #fli Members
        self.fli = None
        self.sample_barcode = None
        self.library = None
        self.type = None
        self.file = None
    def getFli(self):
        #Get FLI (flowcell lane index)
        return self.fli


class JSONdata(object):
    #Class to manage the flowcell lane index information of the project
    def __init__(self,json_file=None):
        self.json_file = json_file
        self.sampleData = {}
        self.config = {}

        with open(self.json_file, 'r') as fileJson:
            jsconfig = json.load(fileJson)
            try:
                conf = jsconfig['config']
                defaults = conf['DEFAULT']
                for sect in ['mapping', 'calling', 'filtering', 'bigwig']:
                    self.config[sect] = {}
                    if conf.has_key(sect):
                        for key,val in conf[sect].iteritems():
                            self.config[sect][key] = val
                    for key,val in defaults.iteritems():
                        if not conf[sect].has_key(key):
                            self.config[sect][key] = val
            except KeyError:
                self.config = {}
            data=jsconfig['sampleData']
            for fli in data:
                fliCommands = Fli()            
                fliCommands.fli = fli
                for key, value in data[fli].iteritems():
                    if key == "sample_barcode":
                        fliCommands.sample_barcode = value    
                    elif key == "library_barcode":
                        fliCommands.library = value    
                    elif key == "type":
                        fliCommands.type = value
                    elif key == "file":
                        fliCommands.file = value

                    self.sampleData[fli] = fliCommands

    def check(self, section, key, arg, default=None, boolean=False, dir_type=False):
        if not arg and self.config[section].has_key(key):
            ret = self.config[section][key]
        else:
            ret = default
        if boolean:
            ret = json.loads(ret.lower())
        elif dir_type:
            ret = ret.rstrip('/')
        return ret

class BasicPipeline(Command):
    """General mapping pipeline class."""

    def __init__(self):
        # general parameter
        self.input = None # input files
        self.output = None #Output files
        self.output_dir = "."
        self.tmp_dir = "/tmp/"
        self.threads = "1"
        
        self.membersInitiation()
        
    def membersInitiation(self):
        #To fullfill in the child class
        pass
        
    def log_parameter(self):
        """Print selected parameters"""
        printer = logging.gemBS.gt
      
        printer("------------ Input Parameter ------------")
        printer("Input File(s)    : %s", self.input)
        printer("Output File(s)   : %s", self.output)
        printer("Output Directory : %s", self.output_dir)
        printer("TMP Directory    : %s", self.tmp_dir)
        printer("Threads          : %s", self.threads)
        printer("")
       
        self.extra_log()
        
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        pass


class PrepareConfiguration(Command):
    title = "Prepare Configuration"
    description = """ Creates a json configuration file to perform the different steps of the Bisulfite pipeline.
                      
                      Input Files:
                          Option 1: Simple text file, comma separated with 5 columns.
                          FORMAT: sample_id,library,flowcell,lane,index
                          
                          Option 2: CNAG Lims Subproject json file

                          In addition, a config file with default parameters for the gemBS commands can also be supplied.
                    
                      If you are managing CNAG bisulfite sequencing data and you have acces to the CNAG lims then Option 2 is the most user friendly.
                      Otherwise Option 1.
                  """
                
    def register(self, parser):
        ## required parameters
        parser.add_argument('-t', '--text-metadata', dest="text_metadata", help="""Metadata configured in 5 columns text file. Comma separated values (CSV) file.
                                                                                   FORMAT:  sample_id,library,flowcell,lane,index                                                                           
                                                                                """,default=None)
        parser.add_argument('-l', '--lims-cnag-json', dest="lims_cnag_json", help="""Lims Cnag subproject json file.""",default=None)
        parser.add_argument('-c', '--config', dest="config", help="""Text config file with gemBS parameters.""",default=None)
        parser.add_argument('-j', '--json', dest="json", help='JSON ouput file',required=True)
        
    def run(self,args):        
        #Try text metadata file
        if args.text_metadata is not None:
            if os.path.isfile(args.text_metadata):
                gemBS.prepareConfiguration(text_metadata=args.text_metadata,jsonOutput=args.json,configFile=args.config)
            else:
                raise CommandException("Sorry!! File %s not found!" %(args.text_metadata))
        elif args.lims_cnag_json is not None:
            if os.path.isfile(args.lims_cnag_json):
                gemBS.prepareConfiguration(lims_cnag_json=args.lims_cnag_json,jsonOutput=args.json,configFile=args.config)
            else:
                raise CommandException("Sorry!! File %s not found!" %(args.lims_cnag_json))
        else:
            raise CommandException("No input file inserted!!")
                    
     
class Index(BasicPipeline):
    title = "Index genomes"
    description = """Reference indexing for Bisulfite GEM mapping 
                     Generates a file called reference.BS.gem (Index) and 
                     reference.BS.info (Information about the index process) 
    """

    def register(self, parser):
        ## required parameters
        parser.add_argument('-i', '--input', dest="input", help='Path to a single fasta reference genome file.',required=True)
        parser.add_argument('-o', '--output_dir', dest="output_dir", help='Directory for output files')
        parser.add_argument('-n', '--name', dest="name", help='Base name for index files')
        parser.add_argument('-t', '--threads', dest="threads", help='Number of threads. By default GEM indexer will use the maximum available on the system.',default=None)
        parser.add_argument('-d', '--list-dbSNP-files',dest="list_db_snp_files",nargs="+",metavar="FILES",
                            help="List of dbSNP files (can be compressed) to create an index to later use it at the bscall step. The bed files should have the name of the SNP in column 4.",default=[],required=False)
        parser.add_argument('-x', '--dbsnp-index', dest="dbsnp_index", help='dbSNP output index file name.',default="",required=False)

    def run(self, args):
        self.input = args.input
        self.threads = args.threads
        self.list_dbSNP_files = args.list_db_snp_files
        self.dbsnp_index = args.dbsnp_index
        if len(self.list_dbSNP_files)>0:     
            if self.dbsnp_index == "":
                raise CommandException("dbSNP Index file must be specified through --dbsnp-index parameter.")
        
        if not os.path.exists(self.input):
            raise CommandException("Input file not found : %s" % self.input)

        self.name = args.name
        if not self.name:
            # No base name supplied so we derive it from input file
            reg = re.compile("(.*)([.][^.]+)$")
            self.name = os.path.basename(self.input)
            m = reg.match(self.name)
            if m and m.group(2).lower() in ['.gz','.xz','.bz2','.z']:
                self.name = m.group(1)
                m = reg.match(self.name)
            if m and m.group(2).lower() in ['.fasta','.fa','.fna','.fn']:
                self.name = m.group(1)

        if self.name.endswith('.gem'): self.name = self.name[:-4]
        if not self.name.endswith('.BS'): self.name += '.BS'
        if args.output_dir: self.name = makeFileName(args.output_dir,self.name)

        self.log_parameter()
        logging.gemBS.gt("Creating index")
        ret = gemBS.index(self.input, self.name, threads=self.threads,tmpDir=args.output_dir,list_dbSNP_files=self.list_dbSNP_files,dbsnp_index=self.dbsnp_index)
        if ret:
            logging.gemBS.gt("Index done: %s.gem" %(ret))
            
       
class MappingCommands(BasicPipeline):
    title = "Show Mapping commands"
    description = """ From a json input file, generates the set of mapping commands to run for mapping all Bisulfite data involved in a Project """

    def register(self,parser):
        ## required parameters
        parser.add_argument('-I', '--index', dest="index", metavar="index_file.BS.gem", help='Path to the Bisulfite Index Reference file.', required=False)
        parser.add_argument('-j', '--json', dest="json_file", metavar="JSON_FILE", help='JSON file configuration.', required=True)
        parser.add_argument('-i', '--input-dir', dest="input_dir", metavar="PATH", help='Directory where is located input data. FASTQ or BAM format.', required=False)
        parser.add_argument('-o', '--output-dir', dest="output_dir", metavar="PATH", help='Directory to store Bisulfite mapping results. Default: .')
        parser.add_argument('-d', '--tmp-dir', dest="tmp_dir", metavar="PATH", help='Temporary folder to perform sorting operations. Default: /tmp')      
        parser.add_argument('-t', '--threads', dest="threads", help='Number of threads to perform sorting operations. Default: %s' %self.threads)
        parser.add_argument('-p', '--paired-end', dest="paired_end", action="store_true", help="Input data is Paired End")
        parser.add_argument('-s', '--read-non-stranded', dest="read_non_stranded", action="store_true", 
                            help='Automatically selects the proper C->T and G->A read conversions based on the level of Cs and Gs on the read.') 
        parser.add_argument('-n', '--underconversion-sequence', dest="underconversion_sequence", metavar="SEQUENCE", help='Name of Lambda Sequence used to control unmethylated cytosines which fails to be\
                             deaminated and thus appears to be Methylated.', default=None, required=False)
        parser.add_argument('-v', '--overconversion-sequence', dest="overconversion_sequence", metavar="SEQUENCE", help='Name of Lambda Sequence used to control methylated cytosines which are\
                             deaminated and thus appears to be Unmethylated.', default=None, required=False)
        
        
    def run(self,args):
        from sets import Set
        paired_types = Set(['PAIRED', 'INTERLEAVED', 'PAIRED_STREAM'])

        ## All Flowcell Lane Index        
        jsonData = JSONdata(args.json_file)

        args.index = jsonData.check(section='mapping',key='gem_index',arg=args.index)
        args.input_dir = jsonData.check(section='mapping',key='sequence_dir',arg=args.input_dir,dir_type=True)
        args.tmp_dir = jsonData.check(section='mapping',key='tmp_dir',arg=args.tmp_dir,default='/tmp',dir_type=True)
        args.threads = jsonData.check(section='mapping',key='threads',arg=args.threads,default='1')
        args.read_non_stranded = jsonData.check(section='mapping',key='non_stranded',arg=args.read_non_stranded,boolean=True)
        args.underconversion_sequence = jsonData.check(section='mapping',key='underconversion_sequence',arg=args.underconversion_sequence)
        args.overconversion_sequence = jsonData.check(section='mapping',key='overconversion_sequence',arg=args.overconversion_sequence)
        args.output_dir = jsonData.check(section='mapping',key='bam_dir',arg=args.output_dir,default='.',dir_type=True)
        output_sample = '@SAMPLE' in args.output_dir
        input_sample = '@SAMPLE' in args.input_dir
        for k,v in jsonData.sampleData.iteritems():
            ##Non Stranded
            non_stranded = ""
            if args.read_non_stranded:
                non_stranded += "-s"
            ## Conversion Parameters
            conversion_parameters = ""            
            if args.underconversion_sequence is not None:  
                conversion_parameters += " -n %s" %(args.underconversion_sequence)
            if args.overconversion_sequence is not None:  
                conversion_parameters += " -v %s" %(args.overconversion_sequence)
            if output_sample:
                output = args.output_dir.replace('@SAMPLE',v.sample_barcode)
            else:
                output = args.output_dir
            if input_sample:
                input_dir = args.input_dir.replace('@SAMPLE',v.sample_barcode)
            else:
                input_dir = args.input_dir
            paired = args.paired_end
            if paired == None:
                if v.type in paired_types:
                    paired = True
            if paired:
                print "gemBS mapping -I %s -f %s -j %s -i %s -o %s -d %s -t %s -p %s %s"\
                       %(args.index,k,args.json_file,input_dir,output,args.tmp_dir,str(args.threads),non_stranded,conversion_parameters)
            else:
                print "gemBS mapping -I %s -f %s -j %s -i %s -o %s -d %s -t %s %s %s"\
                      %(args.index,k,args.json_file,input_dir,output,args.tmp_dir,str(args.threads),non_stranded,conversion_parameters)
            
        
class Mapping(BasicPipeline):
    title = "Bisulphite mapping"
    description = """Maps a single end or paired end bisulfite sequence using the gem mapper. 
     
    Each time a mapping is called a fastq file is mapped. (Two Paired fastq files in case of paired end).
    Files must be located in an input directory in the form: FLOWCELL_LANE_INDEX.suffix
                  
    Suffix could be: _1.fq _2.fq _1.fastq _2.fastq _1.fq.gz _2.fq.gz _1.fastq.gz _2.fastq.gz for paired end.
    .fq .fq.gz .fastq .fastq.gz for single end or interleaved paired end files.

    Suffix could also be .bam in case of aligned files.
                  
    Example:
    gemBS mapping -I ref.BS.gem --fli flowcellname_lanename_indexname --json myfile.json --input-dir INPUTPATH --output-dir OUTPUTPATH --tmp-dir $TMPDIR --threads 8 -p
    
    """   
 
    def register(self,parser):
        ## required parameters
        parser.add_argument('-j', '--json', dest="json_file", metavar="JSON_FILE", help='JSON file configuration.', required=True)
        parser.add_argument('-I', '--index', dest="index", metavar="index_file.BS.gem", help='Path to the Bisulfite Index Reference file.', required=False)
        parser.add_argument('-f', '--fli', dest="fli", metavar="DATA_FILE", help='Data file/file pair to be mapped.', required=False)
        parser.add_argument('-n', '--sample', dest="sample", metavar="DATA_FILE", help='Sample to be mapped.', required=False)
        parser.add_argument('-i', '--input-dir', dest="input_dir", metavar="PATH", help='Directory where is located input data. FASTQ, FASTA, SAM or BAM format.', required=False)
        parser.add_argument('-o', '--output-dir', dest="output_dir", metavar="PATH", help='Directory to store Bisulfite mapping results. Default: .')
        parser.add_argument('-d', '--tmp-dir', dest="tmp_dir", metavar="PATH", help='Temporary folder to perform sorting operations. Default: /tmp')      
        parser.add_argument('-t', '--threads', dest="threads", help='Number of threads to perform sorting operations. Default %s' %self.threads)
        parser.add_argument('-T', '--type', dest="ftype", help='Type of data file (PAIRED, SINGLE, INTERLEAVED, STREAM, BAM)')
        parser.add_argument('-p', '--paired-end', dest="paired_end", action="store_true", help="Input data is Paired End")
        parser.add_argument('-F', '--force', dest="force", action="store_true", help="Force command even if output file exists")
        parser.add_argument('-s', '--read-non-stranded', dest="read_non_stranded", action="store_true", 
                              help='Automatically selects the proper C->T and G->A read conversions based on the level of Cs and Gs on the read.')     
        parser.add_argument('-u', '--underconversion-sequence', dest="underconversion_sequence", metavar="SEQUENCE", help='Name of Lambda Sequence used to control unmethylated cytosines which fails to be\
                              deaminated and thus appears to be Methylated.', default=None,required=False)
        parser.add_argument('-v', '--overconversion-sequence', dest="overconversion_sequence", metavar="SEQUENCE", help='Name of Lambda Sequence used to control methylated cytosines which are\
                              deaminated and thus appears to be Unmethylated.', default=None,required=False)
                    
    def run(self, args):     
        self.all_types = ['PAIRED', 'SINGLE', 'INTERLEAVED', 'BAM', 'SAM', 'STREAM', 'SINGLE_STREAM', 'PAIRED_STREAM']
        self.paired_types = ['PAIRED', 'INTERLEAVED', 'PAIRED_STREAM']
        self.stream_types = ['STREAM', 'SINGLE_STREAM', 'PAIRED_STREAM']

        if args.ftype:
            args.ftype = args.ftype.upper()
            if args.ftype in self.all_types:
                if args.ftype == 'STREAM': 
                    args.ftype = 'PAIRED_STREAM' if args.paired_end else 'SINGLE_STREAM'
                elif args.ftype in self.paired_types:
                    args.paired_end = True
                elif args.paired_end:
                    raise ValueError('Type {} is not paired'.format(args.ftype))
            else:
                raise ValueError('Invalid type specified {}'.format(args.ftype))
        self.ftype = args.ftype

        # JSON data
        self.jsonData = JSONdata(args.json_file)

        self.paired_end = args.paired_end
        self.name = args.sample
        self.index = self.jsonData.check(section='mapping',key='gem_index',arg=args.index)
        if not self.index: raise ValueError("No GEM Index file supplied for mapping operation")
        self.input_dir = self.jsonData.check(section='mapping',key='sequence_dir',arg=args.input_dir,dir_type=True,default='.')
        self.tmp_dir = self.jsonData.check(section='mapping',key='tmp_dir',arg=args.tmp_dir,default='/tmp',dir_type=True)
        self.threads = self.jsonData.check(section='mapping',key='threads',arg=args.threads,default='1')
        self.read_non_stranded = self.jsonData.check(section='mapping',key='non_stranded',arg=args.read_non_stranded, boolean=True)
        self.output_dir = self.jsonData.check(section='mapping',key='bam_dir',arg=args.output_dir,default='.',dir_type=True)
        self.underconversion_sequence = self.jsonData.check(section='mapping',key='underconversion_sequence',arg=args.underconversion_sequence)
        self.overconversion_sequence = self.jsonData.check(section='mapping',key='overconversion_sequence',arg=args.overconversion_sequence)
        #Force flag
        self.force_flag = args.force

        #Check Temp Directory
        if not os.path.isdir(self.tmp_dir):
            raise CommandException("Temporary directory %s does not exists or is not a directory." %(self.tmp_dir))

        if args.fli:
            self.do_mapping(args.fli)
        else:
            for fli,v in self.jsonData.sampleData.iteritems():
                if self.name and v.sample_barcode != self.name: continue
                self.do_mapping(fli)
                    
    def do_mapping(self, fli):
        
        try:
            fliInfo = self.jsonData.sampleData[fli] 
        except KeyError:
            raise ValueError('Data file {} not found in config file'.format(fli))

        #Paired
        self.paired = self.paired_end
        ftype = self.ftype
        if not self.paired:
            if ftype == None: ftype = fliInfo.type 
            if ftype in self.paired_types: self.paired = True

        input_dir = self.input_dir
        if '@SAMPLE' in input_dir:
            input_dir = input_dir.replace('@SAMPLE',fliInfo.sample_barcode)
        output_dir = self.output_dir
        if '@SAMPLE' in output_dir:
            output_dir = output_dir.replace('@SAMPLE',fliInfo.sample_barcode)
        inputFiles = []
        
        # Find input files
        if not ftype:
            ftype = fliInfo.type
        if not ftype in self.stream_types:
            files = fliInfo.file
            if files:            
                # If filenames were specified in configuration file then use them
                if(ftype == 'PAIRED'):
                    inputFiles = [makeFileName(input_dir,files['1']), makeFileName(input_dir,files['2'])]
                else:
                    for k,v in files.iteritems():
                        if ftype is None:
                            if 'bam' in v: 
                                ftype = 'BAM'
                            elif 'sam' in v:
                                ftype = 'SAM'
                            else:
                                ftype = 'INTERLEAVED' if self.paired else 'SINGLE'
                        inputFiles.append(makeFileName(input_dir,v))
                        break
            else:
                # Otherwise search in input directory for possible data files
                if not os.path.isdir(input_dir):
                    raise ValueError("Input directory {} does not exist".format(input_dir))

                # Look for likely data files in input_dir
                reg = re.compile("(.*){}(.*)(.)[.](fastq|fq|fasta|fa|bam|sam)([.][^.]+)?$".format(fliInfo.getFli()), re.I)
                mlist = []
                for file in os.listdir(input_dir):
                    m = reg.match(file)
                    if m: 
                        if m.group(5) in [None, '.gz', '.xz', 'bz2', 'z']: 
                            if ftype == 'PAIRED' and (m.group(3) not in ['1', '2'] or m.group(4).lower() not in ['fasta', 'fa', 'fastq', 'fq']): continue
                            if ftype in ['SAM', 'BAM'] and m.group(4).lower() not in ['sam', 'bam']: continue
                            mlist.append((file, m))
                            
                if len(mlist) == 1:
                    (file, m) = mlist[0]
                    skip = false
                    if ftype is None:
                        if m.group(4).lower() in ['SAM', 'BAM']:
                            ftype = 'BAM' if m.group(4).lower == 'BAM' else 'SAM'
                        else:
                            ftype = 'INTERLEAVED' if self.paired else 'SINGLE'
                    elif ftype == 'PAIRED' or (ftype == 'SAM' and m.group(4).lower != 'sam') or (ftype == 'BAM' and m.group(4).lower() != 'bam'): skip = True
                    if not skip: inputFiles.append(file)
                elif len(mlist) == 2:
                    (file1, m1) = mlist[0]
                    (file2, m2) = mlist[1]
                    for ix in [1, 2, 4]:
                        if m1.group(ix) != m2.group(ix): break
                    else:
                        if (ftype == None or ftype == 'PAIRED') and m1.group(4) in ['fastq', 'fq', 'fasta', 'fa']:
                            if m1.group(3) == '1' and m2.group(3) == '2':
                                inputFiles = [makeFileName(input_dir,file1), makeFileName(input_dir,file2)]
                            elif m1.group(3) == '2' and m2.group(3) == '1':
                                inputFiles = [makeFileName(input_dir,file2), makeFileName(input_dir,file1)]
                            self.ftype = 'PAIRED'
                            self.paired = True

            if not inputFiles:
                raise ValueError('Could not find input files for {} in {}'.format(fliInfo.getFli(),input_dir))

        self.curr_fli = fli
        self.curr_ftype = ftype
        self.inputFiles = inputFiles
        self.curr_output_dir = output_dir
        self.log_parameter()

        logging.gemBS.gt("Bisulfite Mapping...")
        ret = gemBS.mapping(name=fli,index=self.index,fliInfo=fliInfo,inputFiles=inputFiles,ftype=ftype,
                            read_non_stranded=self.read_non_stranded,force_flag=self.force_flag,
                            outputDir=output_dir,paired=self.paired,tmpDir=self.tmp_dir,threads=self.threads,
                            under_conversion=self.underconversion_sequence,over_conversion=self.overconversion_sequence) 
        
        if ret:
            logging.gemBS.gt("Bisulfite Mapping done. Output File: %s" %(ret))
            
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methods, to be define in child class
        printer = logging.gemBS.gt
        
        printer("------------ Mappings Parameter ------------")
        printer("Name             : %s", self.curr_fli)
        printer("Index            : %s", self.index)
        printer("Paired           : %s", self.paired)
        printer("Read non stranded: %s", self.read_non_stranded)
        printer("Type             : %s", self.curr_ftype)
        if self.inputFiles:
            printer("Input Files      : %s", ','.join(self.inputFiles))
        printer("Output dir       : %s", self.curr_output_dir)
        
        printer("")

class Merging(BasicPipeline):
    title = "Merging bams"
    description = """Merges all bam alignments involved in a given Bisulfite project or for a given sample.
                     Each bam alignment file belonging to a sample should be merged to perform the methylation calling."""
                     
    def register(self,parser):
        ## required parameters                     
        parser.add_argument('-j', '--json', dest="json_file", metavar="JSON_FILE", help='JSON file configuration.', required=True)
        parser.add_argument('-i', '--input-dir', dest="input_dir",metavar="PATH", help='Path where are located the BAM aligned files.', required=False)
        parser.add_argument('-t', '--threads', dest="threads", metavar="THREADS", help='Number of threads, Default: %s' %self.threads)
        parser.add_argument('-o', '--output-dir', dest="output_dir", metavar="PATH",help='Output directory to store merged results.',required=False)
        parser.add_argument('-d', '--tmp-dir', dest="tmp_dir", metavar="PATH", default="/tmp/", help='Temporary folder to perform sorting operations. Default: %s' %self.tmp_dir)
        parser.add_argument('-s', '--sample-id',dest="sample_id",metavar="SAMPLE",help="Sample unique identificator",required=False) 
        parser.add_argument('-F', '--force', dest="force", action="store_true", help="Force command even if output file exists")
        
    def run(self, args):
        # JSON data
        self.jsonData = JSONdata(args.json_file)
        # configuration data
        config = self.jsonData.config['mapping']

        self.input_dir = self.jsonData.check(section='mapping',key='bam_dir',arg=args.input_dir,dir_type=True,default='.')
        self.output_dir = self.jsonData.check(section='mapping',key='merged_bam_dir',arg=args.output_dir,default='.',dir_type=True)
        self.tmp_dir = self.jsonData.check(section='mapping',key='tmp_dir',arg=args.tmp_dir,default='/tmp',dir_type=True)

        #Create Dictionary of samples and bam file        
        self.samplesBams = {}  
        self.records = 0
        for k,v in JSONdata(args.json_file).sampleData.iteritems():
            fli = v.getFli()
            sample = v.sample_barcode
            if args.sample_id and sample != args.sample_id: continue
            input_dir = self.input_dir
            if '@SAMPLE' in input_dir:
                input_dir = input_dir.replace('@SAMPLE',sample)
            fileBam = '{}/{}.bam'.format(input_dir,fli)
            self.records = self.records + 1
            if os.path.isfile(fileBam):
                if sample not in self.samplesBams:
                    self.samplesBams[sample] = [fileBam]
                else:
                    self.samplesBams[sample].append(fileBam) 
                    
        #Check list of files
        self.totalFiles = 0
        for sample,listBams in self.samplesBams.iteritems():
            self.totalFiles += len(listBams)
              
        if self.totalFiles < 1:
            raise CommandException("Sorry no bam files were found")
        elif self.totalFiles != self.records:
            raise CommandException("Sorry not all bam files were found".format(sample))
            
        self.log_parameter()
        logging.gemBS.gt("Merging process started...")
        ret = gemBS.merging(inputs=self.samplesBams,threads=self.threads,output_dir=self.output_dir,tmpDir=self.tmp_dir,force=args.force)
         
        if ret:
            logging.gemBS.gt("Merging process done!! Output files generated:")
            for sample,outputBam  in ret.iteritems():
                logging.gemBS.gt("%s: %s" %(sample, outputBam))
                            
class MethylationCall(BasicPipeline):
    title = "Methylation Calling"
    description = """Performs a methylation calling from a bam aligned file.
                     This process is performed over a list of chromosomes in a sequentially way.
                     If you prefer to run the methylation calls in parallel you should consider bscall
                     command.
                  """
    def membersInitiation(self):
        self.species = "HomoSapiens"
        self.chroms = "chr1 chr2 chr3 chr4 chr5 chr6 chr7 chr8 chr9 chr10 chr11 chr12 chr13 chr14 chr15 chr16 chr17 chr18 chr19 chr20 chr21 chr22 chrX chrY chrM"

                                   
    def register(self, parser):
        ## required parameters
        parser.add_argument('-j','--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.',required=True)
        parser.add_argument('-r','--fasta-reference',dest="fasta_reference",metavar="PATH",help="Path to the fasta reference file.")
        parser.add_argument('-e','--species',dest="species",metavar="SPECIES",default="HomoSapiens",help="Sample species name. Default: %s" %self.species)
        parser.add_argument('-l','--list-chroms',dest="list_chroms",nargs="+",metavar="CHROMS",help="List of chromosomes to perform the methylation pipeline.")
        parser.add_argument('-s','--sample-id',dest="sample_id",metavar="SAMPLE",help="Sample unique identificator")  
        parser.add_argument('-p','--path-bam',dest="path_bam",metavar="PATH_BAM",help='Path where are stored sample BAM files.',default=None)
        parser.add_argument('-q','--mapq-threshold', dest="mapq_threshold", type=int, default=None, help="Threshold for MAPQ scores")
        parser.add_argument('-Q','--qual-threshold', dest="qual_threshold", type=int, default=None, help="Threshold for base quality scores")
        parser.add_argument('-g','--right-trim', dest="right_trim", metavar="BASES",type=int, help='Bases to trim from right of read pair, Default: 0')
        parser.add_argument('-f','--left-trim', dest="left_trim", metavar="BASES",type=int, help='Bases to trim from left of read pair, Default: 5')        
        parser.add_argument('-o','--output-dir',dest="output_dir",metavar="PATH",help='Output directory to store the results.',default=None)
        parser.add_argument('-d','--paired-end', dest="paired_end", action="store_true", default=False, help="Input data is Paired End")
        parser.add_argument('-t','--threads', dest="threads", metavar="THREADS", help='Number of threads, Default: %s' %self.threads)
        parser.add_argument('-P','--jobs', dest="jobs", default=1, type=int, help='Number of parallel jobs')
        parser.add_argument('-u','--keep-duplicates', dest="keep_duplicates", action="store_true", default=False, help="Do not merge duplicate reads.")    
        parser.add_argument('-k','--keep-unmatched', dest="keep_unmatched", action="store_true", default=False, help="Do not discard reads that do not form proper pairs.")
        parser.add_argument('-1','--haploid', dest="haploid", action="store", default=False, help="Force genotype calls to be homozygous")
        parser.add_argument('-C','--conversion', dest="conversion", default=None, help="Set under and over conversion rates (under,over)")
        parser.add_argument('-J','--mapping-json',dest="mapping_json",help='Input mapping statistics JSON files',default=None)
        parser.add_argument('-B','--reference_bias', dest="ref_bias", default=None, help="Set bias to reference homozygote")
        parser.add_argument('-b','--dbSNP-index-file', dest="dbSNP_index_file", metavar="FILE", help="dbSNP index file.")

    def run(self,args):
        # JSON data
        self.jsonData = JSONdata(args.json_file)
        # configuration data
        config = self.jsonData.config['calling']

        self.threads = self.jsonData.check(section='calling',key='threads',arg=args.threads,default='1')
        self.jobs = self.jsonData.check(section='calling',key='jobs',arg=args.jobs,default='1')
        self.mapq_threshold = self.jsonData.check(section='calling',key='mapq_threshold',arg=args.mapq_threshold)
        self.qual_threshold = self.jsonData.check(section='calling',key='qual_threshold',arg=args.qual_threshold)
        self.left_trim = self.jsonData.check(section='calling',key='left_trim',arg=args.left_trim,default='5')
        self.right_trim = self.jsonData.check(section='calling',key='right_trim',arg=args.right_trim,default='0')

        self.fasta_reference = args.fasta_reference 
        self.species = args.species
        self.input_dir = args.path_bam
        self.right_trim = args.right_trim
        self.left_trim = args.left_trim
        self.json_file = args.json_file
        self.output_dir = args.output_dir  
        self.paired = args.paired_end
        self.keep_unmatched = args.keep_unmatched
        self.keep_duplicates = args.keep_duplicates
        self.dbSNP_index_file = args.dbSNP_index_file
        self.mapq_threshold = args.mapq_threshold
        self.bq_threshold = args.mapq_threshold
        self.haploid = args.haploid
        self.conversion = args.conversion
        self.ref_bias = args.ref_bias
        self.jobs = args.jobs
        self.list_chroms = []
        self.sample_conversion = {}

        if self.conversion != None and self.conversion.lower() == "auto":
            if args.mapping_json == None or args.json_file == None:
                self.conversion = None
            else:
                sample_lane_files = {}
                for k,v in JSONdata(args.json_file).sampleData.iteritems():
                    fileJson = "%s/%s.json" %(args.mapping_json,v.getFli())
                    if os.path.isfile(fileJson):
                        if v.sample_barcode not in sample_lane_files: 
                            newFli = {}
                            newFli[v.getFli()] = [fileJson]
                            sample_lane_files[v.sample_barcode] = newFli
                        elif v.getFli() not in sample_lane_files[v.sample_barcode]:
                            newFli = {}
                            newFli[v.getFli()] = [fileJson]
                            sample_lane_files[v.sample_barcode].update(newFli)
                        elif v.getFli() in sample_lane_files[v.sample_barcode]:
                            sample_lane_files[v.sample_barcode][v.getFli()].append(fileJson)
                
                if len(sample_lane_files) < 1:
                    self.conversion = None
                else:
                    for sample,fli_json in sample_lane_files.iteritems():
                        list_stats_lanes = []
                        for fli,json_files in fli_json.iteritems():  
                            for json_file in json_files:
                                lane = LaneStats(name=fli,json_file=json_file)
                                list_stats_lanes.append(lane)
                    stats = SampleStats(name=sample,list_lane_stats=list_stats_lanes)
                    uc = stats.getUnderConversionRate()
                    oc = stats.getOverConversionRate()
                    if uc == "NA":
                        uc = 0.99
                    elif uc < 0.8:
                        uc = 0.8
                    if oc == "NA":
                        oc = 0.05
                    elif oc > 0.2:
                        oc = 0.2
                    self.sample_conversion[sample] = "{:.4f},{:.4f}".format(1-uc,oc)

        if len(args.list_chroms) > 1:
            self.list_chroms = args.list_chroms
        elif os.path.isfile(args.list_chroms[0]):
            #Check if List_chroms is a file or just a list of chromosomes
            #Parse file to extract chromosme list 
            with open(args.list_chroms[0] , 'r') as chromFile:
                for line in chromFile:
                    self.list_chroms.append(line.rstrip())
        else:
            self.list_chroms = args.list_chroms          
        
        #Check fasta existance
        if not os.path.isfile(args.fasta_reference):
            raise CommandException("Sorry path %s was not found!!" %(args.fasta_reference))
        
        #Check input bam existance
        self.sampleBam = {}
        for k,v in JSONdata(args.json_file).sampleData.iteritems():
            fileBam = "%s/%s.bam" %(self.input_dir,v.sample_barcode)

            if not os.path.isfile(fileBam):
                raise CommandException("Sorry path %s was not found!!" %(fileBam))

            if v.sample_barcode not in self.sampleBam:
                self.sampleBam[v.sample_barcode] = fileBam
        
        #Call for everything
        self.log_parameter()
        logging.gemBS.gt("Methylation Calling...")
        if len(args.list_chroms) > 0:
            ret = gemBS.methylationCalling(reference=self.fasta_reference,species=self.species,
                                         right_trim=self.right_trim, left_trim=self.left_trim,
                                         sample_bam=self.sampleBam,chrom_list=self.list_chroms,
                                         output_dir=self.output_dir,paired_end=self.paired,keep_unmatched=self.keep_unmatched,
                                         keep_duplicates=self.keep_duplicates,dbSNP_index_file=self.dbSNP_index_file,threads=self.threads,jobs=self.jobs,
                                         mapq_threshold=self.mapq_threshold,bq_threshold=self.bq_threshold,
                                         haploid=self.haploid,conversion=self.conversion,ref_bias=self.ref_bias,sample_conversion=self.sample_conversion)

            if ret:
                logging.gemBS.gt("Methylation call done, samples performed: %s" %(ret))
                
                
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        printer = logging.gemBS.gt
        
        printer("----------- Methylation Calling --------")
        printer("Reference       : %s", self.fasta_reference)
        printer("Species         : %s", self.species)
        printer("Right Trim      : %i", self.right_trim)
        printer("Left Trim       : %i", self.left_trim)
        printer("Chromosomes     : %s", self.list_chroms)
        printer("json File       : %s", self.json_file)
        printer("Threads         : %s", self.threads)
        if self.dbSNP_index_file != "":
            printer("dbSNP File      : %s", self.dbSNP_index_file)
        for sample,input_bam in self.sampleBam.iteritems():
            printer("Sample: %s    Bam: %s" %(sample,input_bam))
        printer("")

class MethylationFilteringThread(th.Thread):
    def __init__(self, threadID, methFilt, lock):
        th.Thread.__init__(self)
        self.threadID = threadID
        self.methFilt = methFilt
        self.bcf_list = methFilt.bcf_list
        self.lock = lock

    def run(self):
        while self.bcf_list:
            self.lock.acquire()
            if self.bcf_list:
                bcf = self.bcf_list.pop(0)
                self.lock.release()
                self.methFilt.do_filter(bcf)
            else:
                self.lock.release()
            
class MethylationFiltering(BasicPipeline):
    title = "Filtering of the output generated by the Methylation Calling."
    description = """ Filters all sites called as homozygous CC or GG with a 
                      probability of genotyping error <= 0.01
                      
                      Subset of dinucleotides called as CC/GG
                  """
                  
    def register(self,parser):
        ## required parameters
        parser.add_argument('-b','--bcf',dest="bcf_file",metavar="PATH",help="BCF Methylation call file", default=None)
        parser.add_argument('-p','--path-bcf',dest="path_bcf",metavar="PATH_BCF",help='Path to sample BCF files.',default=None)
        parser.add_argument('-j','--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.', default=None)
        parser.add_argument('-P','--jobs', dest="jobs", default=1, type=int, help='Number of parallel jobs')
        parser.add_argument('-o','--output-dir',dest="output_dir",metavar="PATH",help='Output directory to store the results.',required=True)
        parser.add_argument('-s','--strand-specific', dest="strand_specific", action="store_true", default=False, help="Output separate lines for each strand.")
        parser.add_argument('-q','--phred-threshold', dest="phred", default="20", help="Min threshold for genotype phred score.")
        parser.add_argument('-I','--inform', dest="inform", default="1", help="Min threshold for informative reads.")
        parser.add_argument('-M','--min-nc', dest="min_nc", default="1", help="Min threshold for non-converted reads for non CpG sites.")
        parser.add_argument('-H','--select-het', dest="select_het", action="store_true", default=False, help="Select heterozygous and homozgyous sites.")
        parser.add_argument('-n','--non-cpg', dest="non_cpg", action="store_true", default=False, help="Output non-cpg sites.")
        
    def run(self,args):
        self.output_dir = args.output_dir
        self.path_bcf = args.path_bcf
        self.strand_specific = args.strand_specific
        self.select_het = args.select_het
        self.non_cpg = args.non_cpg
        self.phred = args.phred
        self.inform = args.inform
        self.min_nc = args.min_nc
        self.bcf_list = []
        self.threads = args.jobs
        
        if args.bcf_file == None:
            if args.path_bcf != None and args.json_file != None:
                for k,v in JSONdata(args.json_file).sampleData.iteritems():
                    bcf = "{}/{}.raw.bcf".format(self.path_bcf,v.sample_barcode)
                    if v.sample_barcode not in self.bcf_list:
                        if os.path.isfile(bcf):
                            self.bcf_list.append(v.sample_barcode)
            if not self.bcf_list:
                raise ValueError("No BCF files found to filter.")
        else:
            #Check bcf file existance
            if not os.path.isfile(args.bcf_file):
                raise CommandException("Sorry path %s was not found!!" %(args.bcf_file))
            else:
                self.bcf_list.append(args.bcf_file)

        self.log_parameter()
        logging.gemBS.gt("Methylation Filtering...")
        if args.jobs > 1:
            threads = []
            lock = th.Lock()
            for ix in range(args.jobs):
                thread = MethylationFilteringThread(ix, self, lock)
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()
        else:
            for sample in self.bcf_list:
                self.do_filter(sample)

    def do_filter(self, sample):
        bcf = "{}/{}.raw.bcf".format(self.path_bcf, sample)
        self.bcf_file = bcf
        #Call methylation filtering
        ret = gemBS.methylationFiltering(bcfFile=bcf,output_dir=self.output_dir,name=sample,strand_specific=self.strand_specific,non_cpg=self.non_cpg,
                                         select_het=self.select_het,inform=self.inform,phred=self.phred,min_nc=self.min_nc)
        if ret:
            logging.gemBS.gt("Methylation filtering of {} done, results located at: {}".format(bcf, ret))
            
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methods, to be define in child class
        
class BsCall(BasicPipeline):
    title = "Bisulfite calling for sample and chromosome."
    description = """ Tool useful for a cluster application manager. Methylation
                      calls for a given sample and chromosome.
                  """
     
    def membersInitiation(self):
        self.species = "HomoSapiens"
             
    def register(self,parser):
        ## required parameters
        parser.add_argument('-r','--fasta-reference',dest="fasta_reference",metavar="PATH",help="Path to the fasta reference file.",required=True)
        parser.add_argument('-e','--species',dest="species",metavar="SPECIES",default="HomoSapiens",help="Sample species name. Default: %s" %self.species)
        parser.add_argument('-s','--sample-id',dest="sample_id",metavar="SAMPLE",help="Sample unique identificator")  
        parser.add_argument('-c','--chrom',dest="chrom",metavar="CHROMOSOME",default=None,help="Chromosome name where is going to perform the methylation call")  
        parser.add_argument('-i','--input-bam',dest="input_bam",metavar="INPUT_BAM",help='Input BAM aligned file.',default=None)
        parser.add_argument('-g','--right-trim', dest="right_trim", metavar="BASES",type=int, default=0, help='Bases to trim from right of read pair, Default: 0')
        parser.add_argument('-f','--left-trim', dest="left_trim", metavar="BASES", type=int, default=5, help='Bases to trim from left of read pair, Default: 5')
        parser.add_argument('-o','--output-dir',dest="output_dir",metavar="PATH",help='Output directory to store the results.',default=None)
        parser.add_argument('-p','--paired-end', dest="paired_end", action="store_true", default=False, help="Input data is Paired End") 
        parser.add_argument('-q','--mapq-threshold', dest="mapq_threshold", type=int, default=None, help="Threshold for MAPQ scores")
        parser.add_argument('-Q','--bq-threshold', dest="bq_threshold", type=int, default=None, help="Threshold for base quality scores")
        parser.add_argument('-t','--threads', dest="threads", metavar="THREADS", default="1", help='Number of threads, Default: %s' %self.threads)     
        parser.add_argument('-k','--keep-unmatched', dest="keep_unmatched", action="store_true", default=False, help="Do not discard reads that do not form proper pairs.")
        parser.add_argument('-1','--haploid', dest="haploid", action="store", default=False, help="Force genotype calls to be homozygous")
        parser.add_argument('-C','--conversion', dest="conversion", default=None, help="Set under and over conversion rates (under,over)")
        parser.add_argument('-j','--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.')
        parser.add_argument('-J','--mapping-json',dest="mapping_json",help='Input mapping statistics JSON files',default=None)
        parser.add_argument('-B','--reference_bias', dest="ref_bias", default=None, help="Set bias to reference homozygote")
        parser.add_argument('-u','--keep-duplicates', dest="keep_duplicates", action="store_true", default=False, help="Do not merge duplicate reads.")
        parser.add_argument('-d','--dbSNP-index-file', dest="dbSNP_index_file", metavar="FILE", help="dbSNP index file.",required=False,default="")

    def run(self,args):
        self.threads = args.threads
        self.reference = args.fasta_reference
        self.species = args.species
        self.input = args.input_bam 
        self.right_trim = args.right_trim
        self.left_trim = args.left_trim        
        self.chrom = args.chrom
        self.sample_id = args.sample_id
        self.output_dir = args.output_dir
        self.paired = args.paired_end
        self.keep_unmatched = args.keep_unmatched
        self.keep_duplicates = args.keep_duplicates
        self.dbSNP_index_file = args.dbSNP_index_file
        self.mapq_threshold = args.mapq_threshold
        self.bq_threshold = args.mapq_threshold
        self.haploid = args.haploid
        self.conversion = args.conversion
        self.ref_bias = args.ref_bias
        
        if self.conversion != None and self.conversion.lower() == "auto":
            if args.mapping_json == None or args.json_file == None:
                self.conversion = None
            else:
                lane_stats_list = []
                for k,v in JSONdata(args.json_file).sampleData.iteritems():
                    if v.sample_barcode == self.sample_id:
                        fileJson = "%s/%s.json" %(args.mapping_json,v.getFli())
                        if os.path.isfile(fileJson):
                            lane_stats_list.append(LaneStats(name=v.getFli(),json_file=fileJson))
                stats = SampleStats(name=self.sample_id,list_lane_stats=lane_stats_list)
                uc = stats.getUnderConversionRate()
                oc = stats.getOverConversionRate()
                if uc == "NA":
                    uc = 0.99
                elif uc < 0.8:
                    uc = 0.8
                if oc == "NA":
                    oc = 0.05
                elif oc > 0.2:
                    oc = 0.2
                self.conversion = "{:.4f},{:.4f}".format(1-uc,oc)

        #Check fasta existance
        if not os.path.isfile(args.fasta_reference):
            raise CommandException("Sorry path %s was not found!!" %(args.fasta_reference))
        
        #Check input bam existance 
        if not os.path.isfile(args.input_bam):
            raise CommandException("Sorry path %s was not found!!" %(args.input_bam))
                        
        #Bs Calling per chromosome
        self.log_parameter()
        logging.gemBS.gt("BsCall per sample and chromosome...")
        
        ret = gemBS.bsCalling (reference=self.reference,species=self.species,input_bam=self.input,chrom=self.chrom,
                             right_trim=self.right_trim, left_trim=self.left_trim,
                             sample_id=self.sample_id,output_dir=self.output_dir,
                             paired_end=self.paired,keep_unmatched=self.keep_unmatched,
                             keep_duplicates=self.keep_duplicates,dbSNP_index_file=self.dbSNP_index_file,threads=self.threads,
                             mapq_threshold=self.mapq_threshold,bq_threshold=self.bq_threshold,
                             haploid=self.haploid,conversion=self.conversion,ref_bias=self.ref_bias)
        if ret:
            logging.gemBS.gt("Bisulfite calling done: %s" %(ret)) 
       
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        printer = logging.gemBS.gt
        
        printer("-------------- BS Call ------------")
        printer("Reference       : %s", self.reference)
        printer("Species         : %s", self.species) 
        printer("Chromosomes     : %s", self.chrom)
        printer("Sample ID       : %s", self.sample_id)
        printer("Threads         : %s", self.threads)
        printer("Right Trim      : %i", self.right_trim)
        printer("Left Trim       : %i", self.left_trim)
                
        if self.dbSNP_index_file != "":
            printer("dbSNP File      : %s", self.dbSNP_index_file)
        printer("")       
            
                  
class BsCallConcatenate(BasicPipeline):
    title = "Concatenation of methylation calls for different chromosomes for a given sample."  
    description = """ Concatenates bcf files comming from different methylation calls of 
                      different chromosomes.
                  """
    
    def register(self,parser):
        ## required parameters
        parser.add_argument('-s','--sample-id',dest="sample_id",metavar="SAMPLE",help="Sample unique identificator",required=True)
        parser.add_argument('-l','--list-bcfs',nargs="+",dest="list_bcfs",metavar="BCFLIST",help="List of bcfs to be concatenated.",required=True)
        parser.add_argument('-o','--output-dir',dest="output_dir",metavar="PATH",help='Output directory to store the results.',default=None)
        
    
    def run(self,args):
        self.list_bcf = args.list_bcfs  
        self.sample_id = args.sample_id
        self.output_dir = args.output_dir
        
        #Check bcf files to concatenate
        if len(args.list_bcfs) < 1:
            raise CommandException("No bcf files to concatenate.")
            
        for bcfFile in args.list_bcfs:
            #Check bcf existance 
            if not os.path.isfile(bcfFile):
                raise CommandException("Sorry path %s was not found!!" %(bcfFile))
                
        #Bs Calling Concatenate
        self.log_parameter()
        logging.gemBS.gt("BCF concatenate files...")
        args.list_bcfs.sort(key=lambda x: '{0:0>8}'.format(x).lower())        
        ret = gemBS.bsConcat(list_bcfs=self.list_bcf,sample=self.sample_id,output_dir=self.output_dir)
        if ret:
            logging.gemBS.gt("BCF Concatenation Done: %s" %(ret))
            
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        printer = logging.gemBS.gt
        
        printer("------- BS Call Concatenate ----------")
        printer("List BCF        : %s", self.list_bcf)
        printer("Sample ID       : %s", self.sample_id)
        printer("")       
            
      

      
class MappingReports(BasicPipeline):
    title = "Bisulfite Mapping reports. Builds a HTML and SPHINX report per lane and Sample."
    description = """ From json files lane stats, builds a HTML and SPHINX report per lane and sample """
    
    def register(self,parser):
        ## Mapping report stats parameters
        parser.add_argument('-j', '--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.',required=True)
        parser.add_argument('-i', '--input-dir', dest="input_dir",metavar="PATH", help='Path where to the JSON stat files.', required=True)
        parser.add_argument('-n', '--name', dest="name", metavar="NAME", help='Output basic name',required=True)
        parser.add_argument('-o', '--output-dir', dest="output_dir", metavar="PATH",help='Output directory to store html report.',required=True)
         
         
    def run(self, args):
        self.name = args.name
        self.output_dir = args.output_dir
        
        #Recover json files from input-dir according to json file
        self.sample_lane_files = {}   
      
        self.records = 0
        for k,v in JSONdata(args.json_file).sampleData.iteritems():
            self.records = self.records + 1
            fileJson = "%s/%s.json" %(args.input_dir,v.getFli())
            if os.path.isfile(fileJson):
                if v.sample_barcode not in self.sample_lane_files: 
                   newFli = {}
                   newFli[v.getFli()] = [fileJson]
                   self.sample_lane_files[v.sample_barcode] = newFli
                elif v.getFli() not in self.sample_lane_files[v.sample_barcode]:
                   newFli = {}
                   newFli[v.getFli()] = [fileJson]
                   self.sample_lane_files[v.sample_barcode].update(newFli)
                elif v.getFli() in self.sample_lane_files[v.sample_barcode]:
                    self.sample_lane_files[v.sample_barcode][v.getFli()].append(fileJson)     
               
        #Check list of files
        if len(self.sample_lane_files) < 1:
            raise CommandException("Sorry no json files were found!!")

        self.log_parameter()
        logging.gemBS.gt("Building html reports...")
        report.buildReport(inputs=self.sample_lane_files,output_dir=self.output_dir,name=self.name)
        logging.gemBS.gt("Building sphinx reports...")
        sphinx.buildReport(inputs=self.sample_lane_files,output_dir="%s/SPHINX/" %(self.output_dir),name=self.name)
        logging.gemBS.gt("Report Done.")
         
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        printer = logging.gemBS.gt
        
        printer("------- Mapping Report ----------")
        printer("Name            : %s", self.name)
        printer("")             
        
class VariantsReports(BasicPipeline):
    title = "BS Calls reports. Builds a HTML and SPHINX report per Sample."
    description = """ From chromosome stats json files, builds a HTML and SPHINX report per Sample """

    def register(self,parser):
        ## variants reports stats parameters
        parser.add_argument('-j','--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.',required=True)
        parser.add_argument('-i', '--input-dir', dest="input_dir",metavar="PATH", help='Path were are located the JSON variants stats files.', required=True)
        parser.add_argument('-n', '--name', dest="name", metavar="NAME", help='Output basic name',required=True)
        parser.add_argument('-o', '--output-dir', dest="output_dir", metavar="PATH",help='Output directory to store html and Sphinx Variants report.',required=True)
        parser.add_argument('-t', '--threads', dest="threads", type=int, default=1,help='Number of jobs to run in parallel.',required=False)
        
    def run(self, args):
        self.name = args.name
        self.output_dir = args.output_dir
        self.json_file = args.json_file
       
        #Recover json files from input-dir according to json file
        self.json_files = []
        for file in os.listdir(args.input_dir):
            if file.endswith(".json"):
                self.json_files.append(file)
            
        self.sample_chr_files = {}
        self.sample_list = {}
        
        for k,v in JSONdata(args.json_file).sampleData.iteritems():
            self.sample_list[v.sample_barcode] = 0

        for sample,num in self.sample_list.iteritems():
            for fileJson in self.json_files:
                if fileJson.startswith(sample):
                    self.sample_chr_files[sample] = []
                    self.sample_chr_files[sample].append(args.input_dir + '/' + fileJson)
            
                
        self.log_parameter()
        logging.gemBS.gt("Building Bs Calls html and sphinx reports...")
        bsCallReports.buildBscallReports(inputs=self.sample_chr_files,output_dir=self.output_dir,name=self.name,threads=args.threads)
        logging.gemBS.gt("Report Done.")                         

    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
        printer = logging.gemBS.gt
        
        printer("------- Variants Reports ----------")
        printer("Name            : %s", self.name)
        printer("Json            : %s", self.json_file)
        printer("")   
        
class CpgBigWigConversionThread(th.Thread):
    def __init__(self, threadID, cpgConv, lock):
        th.Thread.__init__(self)
        self.threadID = threadID
        self.cpgConv = cpgConv
        self.cpg_list = cpgConv.cpg_list
        self.lock = lock

    def run(self):
        while self.cpg_list:
            self.lock.acquire()
            if self.cpg_list:
                tup = self.cpg_list.pop(0)
                self.lock.release()
                self.cpgConv.do_conversion(tup)
            else:
                self.lock.release()
                
class CpgBigwig(BasicPipeline):
    title = "Build BigWig files."
    description = """ Creates BigWig files to show pipeline results in Genome Browsers.
                      
                      Input Files:
                          CpG: Compressed CpG File to be transformed to Methylation and Coverage BigWig files.
                          Chromosome Sizes: File of chromosome lengths
                    
                      Creates methylation and coverage BigWig files.
                  """
                
    def register(self, parser):
        ## required parameters
        parser.add_argument('-c','--cpg-file', dest="cpg_file", help="""CpG gzipped Compressed File.""",default=None)
        parser.add_argument('-l','--chrom-length', dest="chrom_length", help="""Chromosome Length Text File.
                                                                                 Format: Two Columns: <chromosome name> <size in bases>""",required=True,default=None)
        parser.add_argument('-p','--path-cpg',dest="path_cpg",metavar="PATH_CPG",help='Path to sample CPG files.',default=None)
        parser.add_argument('-P','--jobs', dest="jobs", default=1, type=int, help='Number of parallel jobs')
        parser.add_argument('-n','--name', dest="name", metavar="NAME", help='Output basic name',default=None)
        parser.add_argument('-j','--json',dest="json_file",metavar="JSON_FILE",help='JSON file configuration.', default=None)
        parser.add_argument('-q', '--quality', dest="quality", metavar="QUAL", help='Quality filtering criteria for the CpGs. By default 20.',required=False,default="20")
        parser.add_argument('-i', '--informative-reads', dest="informative_reads", metavar="READS", help='Total number of informative reads to filter CpGs.By default 5.',required=False,default="5")   
        parser.add_argument('-o','--output-dir',dest="output_dir",metavar="PATH",help='Output directory to store the results.',required=True,default=None)
                                                                                 
    def run(self,args):        
        self.name = args.name
        self.output_dir = args.output_dir
        self.cpg_file = args.cpg_file
        self.chrom_length = args.chrom_length
        self.quality = args.quality
        self.informative_reads = args.informative_reads
        self.threads = args.jobs
        self.cpg_list = []

        #Check chromosome length file existance
        if not os.path.isfile(args.chrom_length):
            raise CommandException("Sorry path %s was not found!!" %(args.chrom_length)) 
        
        if args.cpg_file == None:
            if args.path_cpg != None and args.json_file != None:
                for k,v in JSONdata(args.json_file).sampleData.iteritems():
                    cpg = "{}/{}_cpg.txt.gz".format(args.path_cpg,v.sample_barcode)
                    tup = (v.sample_barcode, cpg)
                    if tup not in self.cpg_list:
                        if os.path.isfile(cpg):
                            self.cpg_list.append(tup)
            if not self.cpg_list:
                raise ValueError("No CPG files found to filter.")
        else:
            #Check CpG gzipped compressed file
            if not os.path.isfile(args.cpg_file):
                raise CommandException("Sorry path %s was not found!!" %(args.cpg_file))
            else:
                if args.name == None:
                    if args.cpg_file.endswith('_cpg.txt.gz'):
                        base = os.path.basename(args.cpg_file)
                        l = len(base) - 11
                        args.name = base[:l]
                self.cpg_list.append((args.name,args.cpg_file))

        self.log_parameter()
        logging.gemBS.gt("CpG BigWig Conversion...")

        if args.jobs > 1:
            threads = []
            lock = th.Lock()
            for ix in range(args.jobs):
                thread = CpgBigWigConversionThread(ix, self, lock)
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()
        else:
            for tup in self.cpg_list:
                self.do_conversion(tup)
        
    def do_conversion(self, tup):
        
        #Cpg BigWig Conversion
        (name, cpg_file) = tup
        ret = gemBS.cpgBigWigConversion(name=name,output_dir=self.output_dir,cpg_file=cpg_file,
                                      chr_len=self.chrom_length,quality=self.quality,informative_reads=self.informative_reads)
        if ret:
            logging.gemBS.gt("CpG Bigwig Conversion Done: %s" %(ret))
            
    def extra_log(self):
        """Extra Parameters to be printed"""
        #Virtual methos, to be define in child class
