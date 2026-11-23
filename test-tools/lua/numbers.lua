-- What the interpreter on board does with numbers that have a point, and
-- which words it keeps for itself, so that an app's input may not be named
-- after one of them.
print("a " .. string.format("%.2f", 12 * 0.621371))
print("b " .. tostring(12 * 0.621371))
print("c " .. tostring(5 * 0.621371))
print("d " .. tostring(2.5) .. " " .. math.type(2.5))
print("e " .. tostring(12) .. " " .. math.type(12))
print("f " .. tostring(2.5 * 2) .. " " .. tostring(10 / 2) .. " " .. tostring(7 // 2) .. " " .. tostring(-0.5))
print("g " .. string.format("%d", 12) .. " " .. string.format("%g", 7.456452) .. " " .. string.format("%.1f", -5))
print("h " .. tostring(math.floor(7.456452 * 100 + 0.5) / 100))
print("i " .. tostring(123456789012345) .. " " .. tostring(-99999999999999.9))
local kept = {}
for _, word in ipairs({"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
    "input", "km", "print", "show", "self", "type", "string", "math"}) do
  if load("local " .. word .. " = 1") == nil then
    kept[#kept + 1] = word
  end
end
print("j " .. #kept .. ": " .. table.concat(kept, " "))
show(string.format("%.2f miles", 12 * 0.621371))
