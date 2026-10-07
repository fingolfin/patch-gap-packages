# Print one line per package clone: <dir> TAB <maintainer>; <maintainer>; ...
# where each maintainer is "FirstNames LastName <Email>".
# Run from the gap-packages directory, as classify-maintainers.py does:
#   gap -q -A -b ../list-maintainers.g < /dev/null
SetPrintFormattingStatus("*stdout*", false);

FormatPerson := function(p)
  local email;
  email := "";
  if IsBound(p.Email) then
    email := p.Email;
  fi;
  return Concatenation(p.FirstNames, " ", p.LastName, " <", email, ">");
end;

dirs := Filtered(DirectoryContents("."),
                 d -> IsExistingFile(Concatenation(d, "/PackageInfo.g")));
Sort(dirs);

for d in dirs do
  Unbind(GAPInfo.PackageInfoCurrent);
  Read(Concatenation(d, "/PackageInfo.g"));
  info := GAPInfo.PackageInfoCurrent;
  if not IsBound(info.Persons) then
    Print(d, "\tERROR: no Persons\n");
    continue;
  fi;

  maintainers := Filtered(info.Persons,
                          p -> IsBound(p.IsMaintainer) and p.IsMaintainer = true);
  Print(d, "\t", JoinStringsWithSeparator(List(maintainers, FormatPerson), "; "), "\n");
od;
QUIT;
